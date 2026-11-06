from copy import deepcopy
import random
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6 import QtCore, QtTest, QtWidgets

import bots
import core
import humans
import main
from analytics import tags_for_hand
from controller import GameController
from history_store import HistoryStore


APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def human_env(seat="A"):
    other = "B" if seat == "A" else "A"
    return {seat + "_PROVIDER": humans.PROVIDER, seat + "_BASE_URL": humans.BASE_URL,
            seat + "_MODEL": "真人", seat + "_NAME": "我",
            other + "_PROVIDER": "内置机器人", other + "_BASE_URL": bots.BASE_URL,
            other + "_MODEL": "紧凶", other + "_NAME": "机器人"}


class HumanControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite3")
        self.c = GameController(self.store)
        self.views, self.events = [], []
        self.c.viewModelChanged.connect(self.views.append)
        self.c.eventRaised.connect(self.events.append)
        self.c.load_env(human_env())
        self.c.start_new_match(10000, 50, 100, seed=42)
        self.c.bot_delay_ms = 0

    def tearDown(self):
        self.c.set_auto_running(False)
        self.c.deleteLater()
        APP.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def test_wait_has_no_request_or_timeout_and_human_action_resumes(self):
        c = self.c
        c.set_auto_running(True)
        c._human_started = time.monotonic() - 3600
        before = deepcopy(c.state.action_history)
        with patch("core.LLMClient", side_effect=AssertionError("真人与机器人都不应请求网络")):
            for _ in range(10):
                c.auto_tick()
            self.assertEqual(before, c.state.action_history)
            self.assertTrue(c.auto_running)
            self.assertFalse(c.thinking)
            self.assertEqual(0, c.model_stats["AI_A"]["decisions"])
            c.execute_human_action("call", trash_talk="来试试我的牌！")
            self.assertEqual(1, c.model_stats["AI_B"]["decisions"])
            APP.processEvents()
            self.assertEqual(2, len(c._trace.record["actions"]))
            self.assertGreater(c.ledger.times["AI_A"][0], 3599)
            self.assertTrue(c.auto_running)
        self.assertTrue(any(e["type"] == "speech" and e["player"] == "AI_A" for e in self.events))
        self.assertIn("来试试我的牌！", str(c._build_llm_messages("AI_B")))

    def test_invalid_amount_and_wrong_turn_are_rejected_without_side_effects(self):
        c = self.c
        before = deepcopy(c.state.stacks)
        for amount in (0, 100000, -1, 200.1, None, True):
            with self.subTest(amount=amount), self.assertRaises(core.UserFacingError):
                c.execute_human_action("raise", amount, "不应发出")
        self.assertEqual(before, c.state.stacks)
        self.assertEqual([], c._trace.record["actions"])
        self.assertEqual("", c._last_trash_talk["AI_A"])
        with self.assertRaises(core.UserFacingError):
            c.execute_action("raise", 100000)
        c.execute_human_action("call")
        with self.assertRaises(core.UserFacingError):
            c.execute_human_action("check")

    def test_vm_and_events_hide_private_information_then_reveal_at_hand_end(self):
        c = self.c
        self.assertEqual(["??", "??"], self.views[-1].hole_cards["AI_B"])
        self.assertTrue(all(self.views[-1].hole_cards["AI_A"]))
        self.assertFalse(self.views[-1].show_equity)
        c.execute_human_action("call")
        c.active_request_id = 12
        c.thinking = True
        c.thinking_started = time.monotonic()
        c._handle_llm_result(12, "AI_B", '{"action":"check","analysis":"私有牌力分析","trash_talk":"来吧"}', "")
        self.assertNotIn("AI_B", self.views[-1].last_analysis)
        self.assertFalse(any(e["type"] == "reasoning" for e in self.events))
        c.set_god_view(True)
        self.assertNotIn("??", self.views[-1].hole_cards["AI_B"])
        self.assertEqual("私有牌力分析", self.views[-1].last_analysis["AI_B"])
        c.set_god_view(False)
        c.advance_street()
        c.execute_action("bet", 100)
        c.execute_human_action("fold")
        self.assertTrue(any(e["type"] == "reasoning" and "本手揭晓" in e["text"] for e in self.events))
        self.assertEqual(["??", "??"], self.views[-1].hole_cards["AI_B"])
        hand = self.store.get_hand(c.match_id, 1)
        self.assertEqual("human", hand["player_types"]["AI_A"])
        self.assertEqual("真人", hand["models"]["AI_A"])
        self.assertEqual(2, len([d for d in hand["decisions"] if d["player"] == "AI_A"]))

    def test_showdown_reveals_cards_and_human_b_can_play(self):
        c = self.c
        c.load_env(human_env("B"))
        c.start_new_match(10000, 50, 100, seed=42)
        self.assertEqual(["??", "??"], self.views[-1].hole_cards["AI_A"])
        c.execute_action("call", None)
        c.execute_human_action("check")
        for _ in range(3):
            c.advance_street()
            c.execute_human_action("check")
            c.execute_action("check", None)
        c.showdown()
        self.assertTrue(self.views[-1].hand_over)
        self.assertNotIn("??", self.views[-1].hole_cards["AI_A"])
        self.assertFalse(self.views[-1].show_equity)

    def test_commentator_gets_only_public_information_even_with_director_override(self):
        c = self.c
        cards = [core.card_to_text(v) for v in c.state.hole["AI_B"]]
        c._last_analysis["AI_B"] = "秘密分析 " + " ".join(cards)
        c._prev_commentary = "秘密牌 " + " ".join(cards)
        c.commentator.base_url, c.commentator.api_key, c.commentator.model = "https://example.test", "fake", "fake"
        client = MagicMock()
        client.chat.return_value = {"content":"只看公开行动"}
        def thread(**kwargs):
            worker = MagicMock()
            worker.start.side_effect = kwargs["target"]
            return worker
        with patch("controller.threading.Thread", side_effect=thread), patch("core.LLMClient", return_value=client):
            for override in (False, True):
                c.set_god_view(override)
                c._trigger_commentary("公开事件")
                messages = str(client.chat.call_args.kwargs["messages"])
                for text in [*cards, "秘密分析", "秘密牌", *(core.card_to_chinese(card) for card in cards)]:
                    self.assertNotIn(text, messages)
        c.set_god_view(False)
        c._handle_comment_result("迟到的私有解说", c.match_id, 1, 0, private=True)
        self.assertFalse(any(e["text"] == "迟到的私有解说" for e in self.events))

    def test_two_humans_rejected_before_profiles_change(self):
        original = self.c.profile["AI_B"]
        env = human_env()
        env.update(B_PROVIDER=humans.PROVIDER, B_BASE_URL=humans.BASE_URL)
        with self.assertRaises(core.UserFacingError):
            self.c.load_env(env)
        self.assertIs(original, self.c.profile["AI_B"])


class StrategyFixTests(unittest.TestCase):
    def test_bluff_requires_postflop_aggression_and_high_card_at_that_point(self):
        hand = dict(winner="AI_A", reason="fold", street="river", blinds={"bb":100},
                    hole={"AI_A":["Ah","Kd"], "AI_B":["Qh","Jd"]}, board=["6s","8h","Tc","Ac","9h"],
                    actions=[dict(player="AI_A",action="raise",street="preflop"), dict(player="AI_B",action="fold",street="preflop")])
        self.assertNotIn("bluff", tags_for_hand(hand))
        hand["actions"][0].update(action="bet", street="flop", board=["6s","8h","Tc"])
        self.assertIn("bluff", tags_for_hand(hand))
        hand["actions"][0]["board"] = ["As","8h","Tc"]
        self.assertNotIn("bluff", tags_for_hand(hand))
        hand["actions"][0].update(board=["6s","8h","Tc"], hole={"AI_A":["Ts","Td"]})
        self.assertNotIn("bluff", tags_for_hand(hand))

    def test_two_pair_with_own_contribution_rarely_folds_half_pot(self):
        state = core.HandState()
        state.new_match(10000, seed=20)
        state.lock_cards([core.parse_card(c) for c in ("Th","Ts")],
                         [core.parse_card(c) for c in ("Ah","Jc")],
                         [core.parse_card(c) for c in ("6c","6d","7h","Qc","Ks")])
        state.apply_action("AI_A","call",None)
        state.apply_action("AI_B","check",None)
        for _ in range(3):
            state.advance_street()
            if state.street != "river":
                state.apply_action("AI_B","check",None)
                state.apply_action("AI_A","check",None)
        state.apply_action("AI_B","bet",state.pot_cents // 2)
        for style in bots.STYLES:
            folds = sum(bots.decide(state,"AI_A",style,random.Random(seed))["action"] == "fold" for seed in range(200))
            self.assertLessEqual(folds, 5, (style,folds))
        value, own = bots.made_strength(state.hole["AI_A"],state.board)
        board_only = [core.parse_card(c) for c in ("6c","6d","Qh","Qc","Ks")]
        weaker, contribution = bots.made_strength([core.parse_card(c) for c in ("Ah","Jd")],board_only)
        self.assertTrue(own)
        self.assertFalse(contribution)
        self.assertGreater(value, weaker)


class HumanUITests(unittest.TestCase):
    def test_new_match_after_immediate_fold_refreshes_amount_limits(self):
        from human_widgets import HumanDock
        controller = GameController()
        controller.load_env(human_env())
        dock = HumanDock(MagicMock(controller=controller))
        controller.viewModelChanged.connect(dock.update_state)
        try:
            controller.start_new_match(10000, 50, 100)
            self.assertEqual(10000, dock.slider.maximum())
            dock.amount.setValue(80)
            controller._emit_vm()
            self.assertEqual(80, dock.amount.value())
            controller.execute_human_action("fold")
            controller.start_new_match(20000, 50, 100)
            self.assertEqual(20000, dock.slider.maximum())
            self.assertEqual(200, dock.amount.maximum())
            self.assertEqual(2, dock.amount.value())
        finally:
            dock.deleteLater()
            controller.deleteLater()
            APP.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def test_challenge_dock_settings_validation_shortcuts_and_privacy_toggle(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs = QtCore.QSettings(str(Path(folder)/"prefs.ini"),QtCore.QSettings.Format.IniFormat)
            with patch("core.load_dotenv",return_value={}), patch("app_shell.QtCore.QSettings",return_value=prefs):
                window = main.MainWindow()
            try:
                window.show()
                window.shell.challenge()
                self.assertEqual(humans.PROVIDER,window.provider_controls["A"].provider.currentText())
                self.assertEqual(0,window.shell.dialog.nav.currentRow())
                item = window.provider_controls["B"].provider.model().item(window.provider_controls["B"].provider.findText(humans.PROVIDER))
                self.assertFalse(item.isEnabled())
                self.assertNotIn(humans.PROVIDER, [window.provider_controls["COMMENTATOR"].provider.itemText(i) for i in range(window.provider_controls["COMMENTATOR"].provider.count())])
                with patch("core.save_dotenv") as save:
                    window.shell.dialog.save()
                    save.assert_called_once()
                APP.processEvents()
                self.assertTrue(window.shell.configured)
                self.assertTrue(window.vm.human_turn)
                dock = window.shell.human_dock
                self.assertFalse(dock.isHidden())
                self.assertEqual("真人",window.controller._trace.models["AI_A"])
                dock.amount.setValue(1000000)
                self.assertEqual(window.vm.legal.max_to_cents,round(dock.amount.value()*100))
                dock.slider.setValue(dock.slider.minimum())
                self.assertEqual(dock.slider.minimum(),round(dock.amount.value()*100))
                window.activateWindow()
                APP.processEvents()
                dock.speech.setFocus()
                APP.processEvents()
                self.assertIs(dock.speech, APP.focusWidget())
                QtTest.QTest.keyClicks(dock.speech,"CAF")
                window.shell.action_shortcut("F",None)
                self.assertEqual("CAF",dock.speech.text())
                self.assertFalse(window.controller.state.hand_over)
                dock.call.click()
                self.assertEqual("CAF",window.controller._last_trash_talk["AI_A"])
                window.shell.mode.setCurrentText("导演")
                window.shell.god_view.setChecked(True)
                window.controller.emit_event("reasoning","私有推理","AI_B")
                self.assertTrue(any(e["text"]=="私有推理" for e in window.shell.timeline.events))
                window.shell.god_view.setChecked(False)
                self.assertFalse(any(e["text"]=="私有推理" for e in window.shell.timeline.events))
                self.assertFalse(window.shell.sidebar_tabs.isTabVisible(window.shell.raw_index))
                window.provider_controls["B"].provider.setCurrentText(humans.PROVIDER)
                with patch("core.save_dotenv") as save, self.assertRaises(core.UserFacingError):
                    window.on_save_env()
                save.assert_not_called()
            finally:
                window.close()
                window.deleteLater()
                APP.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)
