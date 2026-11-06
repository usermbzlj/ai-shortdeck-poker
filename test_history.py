from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

import core
import main
import bots
from analytics import adjusted_net, aggregate, tags_for_hand
from controller import GameController
from history_export import export_json, export_text, pokerstars
from history_store import HistoryStore
from review_widgets import HistoryWindow, frame_vm, share_image
from stats_widgets import StackChart


APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite3")
        self.c = GameController(self.store)
        self.c.start_new_match(10000, 50, 100, seed=24)
        self.c.state.lock_cards([core.parse_card("Ah"), core.parse_card("Ad")],
                               [core.parse_card("Kh"), core.parse_card("Kd")], [])

    def tearDown(self):
        self.c.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def finished(self):
        self.c.execute_action("raise", 300)
        self.c.execute_action("fold", None)
        return self.store.get_hand(self.c.match_id, 1)

    def test_round_trip_actions_frames_tokens_late_commentary_and_no_keys(self):
        c = self.c
        c.profile["AI_A"].api_key = "never-store-this-key"
        with patch("controller.threading.Thread"):
            c.request_ai_decision()
        c.thinking_started -= 1
        c._handle_llm_result(c.active_request_id, "AI_A",
                            '{"action":"raise","to_cents":300,"analysis":"价值下注","trash_talk":"接招"}', "",
                            {"total_tokens":42, "api_key":"never-store-this-key"})
        c.execute_action("fold", None)
        record = self.store.get_hand(c.match_id, 1)
        self.assertEqual(250, record["actions"][0]["paid_cents"])
        self.assertEqual(300, record["actions"][0]["to_cents"])
        self.assertEqual({"total_tokens":42}, record["decisions"][0]["tokens"])
        self.assertGreaterEqual(record["decisions"][0]["think_seconds"], 1)
        self.assertEqual("价值下注", record["decisions"][0]["analysis"])
        self.assertNotIn("never-store", json.dumps(record))
        self.assertTrue(record["frames"][-1]["hand_over"])
        first_id = c.match_id
        c.start_next_hand()
        c._handle_comment_result("迟到的第一手解说", first_id, 1, 2)
        self.assertEqual("迟到的第一手解说", self.store.get_hand(first_id, 1)["commentary"][0]["text"])
        self.assertEqual([], c._trace.record["commentary"])
        c.start_new_match(10000, 50, 100)
        c._handle_comment_result("上场比赛的解说", first_id, 1, 3)
        self.assertEqual(2, len(self.store.get_hand(first_id, 1)["commentary"]))
        self.assertEqual(1, len(self.store.list_matches()))
        self.assertEqual(1, len(self.store.list_hands(search="价值下注")))
        self.assertEqual([], self.store.list_hands(search="不存在"))
        meta = dict(c._metadata, api_key="never-store-this-key")
        record["decisions"][0]["authorization"] = "never-store-this-key"
        self.store.save_hand(meta, record)
        with self.store.connect() as connection:
            raw = connection.execute("SELECT payload FROM hands").fetchone()[0]
        self.assertNotIn("never-store", raw)
        self.assertIsNone(self.store.get_hand("missing", 1))

    def test_empty_and_disk_error_does_not_break_game(self):
        self.assertEqual([], self.store.list_matches())
        errors = []
        self.c.errorRaised.connect(errors.append)
        with patch.object(self.store, "save_hand", side_effect=OSError("只读")):
            self.c.execute_action("fold", None)
        self.assertTrue(self.c.state.hand_over)
        self.assertIn("只读", errors[0])

    def test_pokerstars_known_hand_snapshot_and_json(self):
        hand = self.finished()
        hand["match_id"] = "known000"
        expected = """PokerStars Hand #known000-1: Short Deck Hold'em No Limit ($0.50/$1.00 USD)
Table 'Short Deck Arena' 2-max Seat #1 is the button
Seat 1: 选手 A ($100.00 in chips)
Seat 2: 选手 B ($100.00 in chips)
选手 A: posts small blind $0.50
选手 B: posts big blind $1.00
*** HOLE CARDS ***
Dealt to 选手 A [Ah Ad]
Dealt to 选手 B [Kh Kd]
选手 A: raises $2.00 to $3.00
选手 B: folds
选手 A collected $4.00 from pot
*** SUMMARY ***
Total pot $4.00 | Rake $0.00
Board []
Short deck: 36 cards, flush beats full house, A6789 is a straight.
"""
        self.assertEqual(expected, pokerstars(hand))
        self.assertEqual("", export_text([]))
        self.assertEqual(1, len(json.loads(export_json([hand]))["hands"]))
        self.assertEqual("-$59.00", core.format_money(-5900))
        self.assertEqual("$0.01", core.format_money(1))

    def test_tags_and_allin_ev_math_and_cached_equity(self):
        hand = self.finished()
        hand.update(hole={"AI_A":["Ah","Kd"], "AI_B":["Qs","Jc"]}, board=[], street="preflop")
        self.assertEqual(["bluff"], tags_for_hand(hand))
        hand.update(street="river", board=["6h","8d","Tc","Qs","Ac"],
                    hole={"AI_A":["Ah","Kd"], "AI_B":["7s","9c"]},
                    winner="AI_A", reason="showdown", pot_cents=2000,
                    all_in=dict(pot_cents=2000, equity={"AI_A":.2,"AI_B":.8,"tie":0}))
        hand["actions"].append(dict(player="AI_A", action="call", street="river", paid_cents=100, legal_actions=["call","fold"]))
        self.assertEqual({"big_pot", "bad_beat", "hero_call"}, set(tags_for_hand(hand)))
        hand.update(start_stacks={"AI_A":10000,"AI_B":10000}, final_stacks={"AI_A":11000,"AI_B":9000})
        self.assertEqual({"AI_A":-600,"AI_B":600}, adjusted_net(hand))
        hand["all_in"]["equity"] = None
        self.assertEqual({"AI_A":1000,"AI_B":-1000}, adjusted_net(hand))
        self.store.save_hand(self.c._metadata, hand)
        self.store.save_equity(hand["match_id"], hand["hand_no"], {"AI_A":.2,"AI_B":.8,"tie":0})
        self.assertIn("bad_beat", self.store.get_hand(hand["match_id"],1)["tags"])
        hand["hole"] = {"AI_A":["Ah","Ad"],"AI_B":["Ks","Kc"]}
        self.assertNotIn("hero_call", tags_for_hand(hand))

    def test_synthetic_stats_denominators_threebet_af_and_empty(self):
        hand = self.finished()
        hand.update(reason="showdown", winner="AI_A", saw_flop=["AI_A","AI_B"],
                    decisions=[dict(player="AI_A",think_seconds=2), dict(player="AI_B",think_seconds=1)],
                    model_stats={"AI_A":dict(decisions=2,invalid_outputs=1,fallbacks=1)})
        hand["actions"] = [
            dict(player="AI_A",street="preflop",action="raise",legal_actions=["raise","call"]),
            dict(player="AI_B",street="preflop",action="raise",legal_actions=["raise","call"]),
            dict(player="AI_A",street="preflop",action="call",legal_actions=["raise","call"]),
            dict(player="AI_A",street="flop",action="bet"),
            dict(player="AI_B",street="flop",action="raise"),
            dict(player="AI_A",street="flop",action="call")]
        stats = aggregate([hand])
        self.assertEqual(1, stats["AI_B"]["threebet"])
        self.assertIsNone(stats["AI_A"]["threebet"])
        self.assertEqual(1, stats["AI_A"]["af"])
        self.assertEqual(float("inf"), stats["AI_B"]["af"])
        self.assertEqual(1, stats["AI_A"]["wtsd"])
        self.assertEqual(1, stats["AI_A"]["wsd"])
        self.assertEqual(.5, stats["AI_A"]["invalid_rate"])
        retried = deepcopy(hand)
        retried["model_stats"]["AI_A"].update(decisions=1,retries=2,invalid_outputs=3)
        self.assertEqual(1, aggregate([retried])["AI_A"]["invalid_rate"])
        self.assertEqual(2, stats["AI_A"]["think_seconds"])
        self.assertIsNone(aggregate([])["AI_A"]["vpip"])
        self.assertEqual(0, aggregate([])["AI_A"]["net_cents"])

    def test_called_river_allin_captures_equity_before_settlement(self):
        c = self.c
        c.state.lock_cards(c.state.hole["AI_A"], c.state.hole["AI_B"],
                           [core.parse_card(v) for v in ("6h","7d","8s","9c","Tc")])
        c.execute_action("call", None)
        c.execute_action("check", None)
        for _ in range(3):
            c.advance_street()
            if c.state.street != "river":
                c.execute_action("check", None)
                c.execute_action("check", None)
        c.execute_action("bet", 9900)
        self.assertIsNone(c._trace.record["all_in"])
        c.execute_action("call", None)
        deadline = time.monotonic() + 3
        while not c._trace.record["all_in"]["equity"] and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertEqual(1, c._trace.record["all_in"]["equity"]["tie"])
        self.assertEqual("river", c._trace.record["all_in"]["street"])
        self.assertEqual(20000, c._trace.record["all_in"]["pot_cents"])
        c.showdown()
        hand = self.store.get_hand(c.match_id, 1)
        self.assertEqual({"AI_A":0,"AI_B":0}, adjusted_net(hand))

    def test_replay_share_selection_exports_and_chart_click(self):
        hand = self.finished()
        viewer = HistoryWindow(self.store)
        viewer.open_history(hand)
        APP.processEvents()
        self.assertTrue(viewer.replay.table.vm.hand_over)
        viewer.replay.set_frame(0)
        self.assertFalse(viewer.replay.table.vm.hand_over)
        viewer.replay.next_frame()
        self.assertNotIn("迟到", viewer.replay.context.toPlainText())
        viewer.replay.toggle()
        self.assertTrue(viewer.replay.clock.isActive())
        viewer.replay.set_frame(999)
        self.assertFalse(viewer.replay.clock.isActive())
        path = Path(self.temp.name) / "share.png"
        image = share_image(hand, path)
        self.assertEqual((1600,1000), (image.width(),image.height()))
        self.assertFalse(QtGui.QImage(str(path)).isNull())
        self.assertFalse(frame_vm(hand,0).hand_over)
        with patch("review_widgets.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(Path(self.temp.name)/"hand.json"),"")):
            viewer.export("json")
        self.assertIn("已导出", viewer.message.text())
        with patch("review_widgets.QtWidgets.QFileDialog.getSaveFileName", return_value=("/nonexistent/hand.txt","")):
            viewer.export("text")
        self.assertIn("失败", viewer.message.text())
        viewer.search.setText("missing")
        self.assertEqual(0, viewer.list.rowCount())
        self.assertFalse(viewer.replay.isEnabled())
        self.assertIsNone(viewer.replay.table.vm)
        viewer.export("json")
        self.assertIn("选择", viewer.message.text())
        viewer.close()
        viewer.deleteLater()
        chart = StackChart()
        chart.resize(400,180)
        from analytics import curve_points
        chart.set_points(curve_points([hand]))
        selected = []
        chart.handClicked.connect(selected.append)
        QtTest.QTest.mouseClick(chart, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(380,80))
        self.assertEqual(hand["hand_no"], selected[0]["hand_no"])
        chart.deleteLater()

    def test_real_bot_delay_clock_and_neutral_empty_status(self):
        prefs = QtCore.QSettings(str(Path(self.temp.name)/"prefs.ini"),QtCore.QSettings.Format.IniFormat)
        with patch("core.load_dotenv",return_value={}), patch("app_shell.QtCore.QSettings",return_value=prefs):
            window = main.MainWindow(history_store=self.store)
            try:
                window.show()
                self.assertNotIn("底池", window.statusBar().currentMessage())
                self.assertEqual(1000, window.controller.bot_delay_ms)
                window.controller.bot_delay_ms = 650
                window.shell.start_demo()
                window.timer.stop()
                spy = QtTest.QSignalSpy(window.board_panel._clock.timeout)
                QtTest.QTest.qWait(260)
                self.assertTrue(window.controller.thinking)
                self.assertGreaterEqual(spy.count(), 2)
                QtTest.QTest.qWait(490)
                self.assertGreaterEqual(window.controller.ledger.times["AI_A"][0], .6)
                self.assertNotEqual(bots.reflection("紧凶","赢"),bots.reflection("松凶","输"))
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()
