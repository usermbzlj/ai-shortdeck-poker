import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets

import bots
import core
import main
import theme
from controller import GameController, LLMProfile, CommentatorProfile
from match import MatchRules, combine_stats


APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.c = GameController()

    def tearDown(self):
        self.c.deleteLater()
        APP.processEvents()

    def test_fixed_hand_end_summary_and_restart(self):
        c = self.c
        c.rules = MatchRules("fixed", 2)
        ended = []
        c.matchFinished.connect(ended.append)
        c.start_new_match(10000, 50, 100, seed=123)
        c.execute_action("fold", None)
        self.assertFalse(c.match_finished)
        c.start_next_hand()
        c.execute_action("fold", None)
        self.assertTrue(c.match_finished)
        self.assertEqual(1, len(ended))
        self.assertEqual(2, ended[0]["hands"])
        self.assertEqual(20000, sum(ended[0]["stacks_cents"].values()))
        self.assertGreater(ended[0]["biggest_pot_cents"], 0)
        self.assertEqual(0, ended[0]["stats"]["AI_A"]["vpip"])
        with self.assertRaises(core.UserFacingError):
            c.start_next_hand()
        c.set_auto_running(True)
        self.assertFalse(c.auto_running)
        c.start_new_match(10000, 50, 100)
        self.assertFalse(c.match_finished)
        self.assertIsNone(c.match_summary)
        with self.assertRaises(core.UserFacingError):
            c.start_duplicate()

    def test_blind_escalation_every_two_hands(self):
        c = self.c
        c.rules = MatchRules("levels", level_hands=2)
        levels = []
        c.blindLevelChanged.connect(levels.append)
        c.start_new_match(100000, 50, 100)
        for hand, blinds in ((1, (50, 100)), (2, (50, 100)), (3, (75, 150)), (4, (75, 150)), (5, (112, 225))):
            self.assertEqual(hand, c.state.hand_id)
            self.assertEqual(blinds, (c.state.sb_cents, c.state.bb_cents))
            if hand < 5:
                c.execute_action("fold", None)
                c.start_next_hand()
        self.assertEqual(2, len(levels))
        self.assertEqual(3, c.active_rules.level(5) + 1)
        c.start_new_match(100000, 50, 100)
        self.assertEqual((50, 100), (c.state.sb_cents, c.state.bb_cents))

    def test_bust_ends_match_and_new_match_clears_previous_stop_state(self):
        c = self.c
        c.start_new_match(100, 50, 100)
        c.state.lock_cards([core.parse_card("Ah"), core.parse_card("Ad")],
                           [core.parse_card("Kh"), core.parse_card("Kd")],
                           [core.parse_card(text) for text in ("6s", "6h", "6d", "7s", "8c")])
        c.execute_action("call", None)
        for street in range(3):
            c.advance_street()
        c.showdown()
        self.assertTrue(c.match_finished)
        self.assertEqual("AI_A", c.match_summary["winner"])
        self.assertEqual({"AI_A": 200, "AI_B": 0}, c.match_summary["stacks_cents"])
        self.assertEqual("bust", c.match_summary["rules"]["format"])
        c._consecutive_failures = 3
        c.start_new_match(100, 50, 100)
        self.assertIsNone(c._paused_reason)
        self.assertEqual(0, c._consecutive_failures)

    def test_seed_and_duplicate_cards_swap_even_with_locked_cards(self):
        first = core.HandState()
        first.new_match(100000, seed=501)
        first.lock_cards([core.parse_card("Ah"), core.parse_card("Kh")], None,
                         [core.parse_card("Qh")])
        deals = []
        for hand in range(4):
            first.ensure_dealt("river")
            deals.append((dict((p, list(cards)) for p, cards in first.hole.items()),
                          list(first.board), first.button))
            if hand < 3:
                first.start_hand()
        second = core.HandState()
        second.new_match(100000, seed=501, deck_sequence=first.deck_sequence, swap_seats=True)
        for hand in range(4):
            second.ensure_dealt("river")
            hole, board, button = deals[hand]
            self.assertEqual(hole["AI_A"], second.hole["AI_B"])
            self.assertEqual(hole["AI_B"], second.hole["AI_A"])
            self.assertEqual(board, second.board)
            self.assertNotEqual(button, second.button)
            if hand < 3:
                second.start_hand()
        seeded = core.HandState()
        same_seed = core.HandState()
        seeded.new_match(seed=33)
        same_seed.new_match(seed=33)
        seeded.ensure_dealt("river")
        same_seed.ensure_dealt("river")
        self.assertEqual(seeded.hole, same_seed.hole)
        self.assertEqual(seeded.board, same_seed.board)
        with self.assertRaises(core.UserFacingError):
            seeded.new_match(deck_sequence=[[core.parse_card("Ah")]])

    def test_automatic_duplicate_combines_identity_results(self):
        c = self.c
        c.rules = MatchRules("fixed", 2, duplicate=True)
        c.hand_interval_seconds = 0
        c.start_new_match(10000, 50, 100, seed=77)
        cards = []
        for hand in range(2):
            c.state.ensure_dealt("river")
            cards.append((list(c.state.hole["AI_A"]), list(c.state.board)))
            c.execute_action("fold", None)
            if not hand:
                c.start_next_hand()
        self.assertTrue(c._duplicate_pending)
        c.set_auto_running(True)
        c.auto_tick()
        self.assertTrue(c.state.replay_swapped)
        for hand in range(2):
            c.state.ensure_dealt("river")
            self.assertEqual(cards[hand][0], c.state.hole["AI_B"])
            self.assertEqual(cards[hand][1], c.state.board)
            c.execute_action("fold", None)
            if not hand:
                c.start_next_hand()
        self.assertTrue(c.match_summary["duplicate"])
        self.assertEqual({"AI_A": 0, "AI_B": 0}, c.match_summary["combined_cents"])
        self.assertIsNone(c.match_summary["winner"])
        self.assertFalse(c.auto_running)
        with self.assertRaises(core.UserFacingError):
            c.start_duplicate()

    def test_duplicate_reflection_uses_combined_result_not_second_leg_stacks(self):
        c = self.c
        c.rules = MatchRules("fixed", 1, duplicate=True)
        for first_profit in (100, 500):
            with self.subTest(first_profit=first_profit), patch.object(c, "_fire_reaction_request") as request:
                c.start_new_match(10000, 50, 100, seed=77)
                c.execute_action("raise", max(200, first_profit))
                if first_profit > 100:
                    c.execute_action("call", None)
                    c.advance_street()
                    c.execute_action("check", None)
                    c.execute_action("bet", 100)
                c.execute_action("fold", None)
                c.start_duplicate()
                request.reset_mock()
                c.execute_action("raise", 300)
                c.execute_action("fold", None)
                self.assertGreater(c.state.stacks["AI_B"], c.state.stacks["AI_A"])
                self.assertEqual(None if first_profit == 100 else "AI_A", c.match_summary["winner"])
                ctx = request.call_args_list[0].args[2]
                self.assertEqual("平局" if first_profit == 100 else "获胜", ctx["result"])
                self.assertIn("两场合计净收益", ctx["final_stacks"])
                self.assertIn(core.format_money(first_profit - 100), ctx["final_stacks"])
                self.assertEqual("2", ctx["total_hands"])
                self.assertEqual(("1", "1"), (ctx["my_wins"], ctx["opp_wins"]))

    def test_stats_and_late_reflections_are_match_scoped(self):
        c = self.c
        c.rules = MatchRules("fixed", 1)
        c.start_new_match(10000, 50, 100)
        generation = c._match_generation
        c.execute_action("raise", 300)
        c.execute_action("call", None)
        while c.state.street != "river":
            c.advance_street()
            c.execute_action("check", None)
            c.execute_action("check", None)
        c.showdown()
        stats = c.match_summary["stats"]
        self.assertEqual(1, stats["AI_A"]["vpip"])
        self.assertEqual(1, stats["AI_A"]["pfr"])
        self.assertEqual(1, stats["AI_B"]["vpip"])
        self.assertEqual(1, stats["AI_A"]["showdown_count"])
        c._handle_reaction_result("AI_A", "赛后感言", "下次再来", generation)
        self.assertEqual("下次再来", c.match_summary["reflections"]["AI_A"])
        c._handle_reaction_result("AI_B", "赛后感言", "", generation)
        self.assertIn("暂不可用", c.match_summary["reflections"]["AI_B"])
        c.start_new_match(10000, 50, 100)
        c._handle_reaction_result("AI_A", "赛后感言", "旧结果", generation)
        self.assertIsNone(c.match_summary)

    def test_format_defaults_validation_and_environment_round_trip(self):
        self.assertEqual(MatchRules(), MatchRules.from_env({}))
        env = dict(MATCH_FORMAT="fixed", MATCH_HANDS="8", BLIND_LEVEL_HANDS="3", DUPLICATE_MATCH="true")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / ".env")
            core.save_dotenv(path, env)
            self.assertEqual(MatchRules("fixed", 8, 3, True), MatchRules.from_env(core.load_dotenv(path)))
        for invalid in ({"MATCH_FORMAT": "bad"}, {"MATCH_HANDS": "0"}, {"BLIND_LEVEL_HANDS": "-2"}):
            with self.assertRaises(ValueError):
                MatchRules.from_env(invalid)
        self.assertGreater(MatchRules("levels", level_hands=1).blinds(50, 100, 33)[1],
                           MatchRules("levels", level_hands=1).blinds(50, 100, 32)[1])

    def test_combined_stats_weight_samples_and_preserve_pending_hybrid_reaction(self):
        first = dict(vpip=1, pfr=.5, showdown_win=1, showdown_count=1,
                     thinking_seconds=2, thinking_count=3, invalid_outputs=1, fallbacks=0)
        second = dict(vpip=0, pfr=0, showdown_win=0, showdown_count=3,
                      thinking_seconds=1, thinking_count=1, invalid_outputs=2, fallbacks=1)
        total = combine_stats({"AI_A": first}, {"AI_A": second}, 2, 6)["AI_A"]
        self.assertEqual(.25, total["vpip"])
        self.assertEqual(.25, total["showdown_win"])
        self.assertEqual(1.75, total["thinking_seconds"])
        self.assertEqual(3, total["invalid_outputs"])
        self.c.profile["AI_A"] = LLMProfile(base_url=bots.BASE_URL, model="紧凶")
        self.c._pending_reactions = 2
        self.c._fire_reaction_request("AI_A", "", {}, "内心")
        self.assertEqual(2, self.c._pending_reactions)
        self.c.commentator = CommentatorProfile(base_url=bots.BASE_URL, api_key="previous-key", model="紧凶")
        with patch("core.LLMClient", side_effect=AssertionError("内置玩家不应作为网络解说员")):
            self.c._trigger_commentary("内置玩家无网络解说")

    def test_real_controller_bots_300_hands_without_http_and_conserve_chips(self):
        c = self.c
        c.rules = MatchRules("fixed", 300)
        c.hand_interval_seconds = 0
        c.bot_delay_ms = 0
        c._bot_rng.seed(492)
        c.profile = {p: LLMProfile(base_url=bots.BASE_URL, model=style)
                     for p, style in (("AI_A", "紧凶"), ("AI_B", "松凶"))}
        c.start_new_match(10000000, 50, 100, seed=492)
        c.set_auto_running(True)
        with patch("core.LLMClient", side_effect=AssertionError("离线模式不应请求 API")):
            for tick in range(30000):
                c.auto_tick()
                APP.processEvents()
                self.assertEqual(20000000, sum(c.state.stacks.values()) + c.state.pot_cents)
                if c.match_finished:
                    break
        self.assertTrue(c.match_finished)
        self.assertEqual(300, c.ledger.hands)
        self.assertEqual(0, sum(s["invalid_outputs"] for s in c.model_stats.values()))
        self.assertEqual(0, sum(s["fallbacks"] for s in c.model_stats.values()))
        self.assertTrue(c.match_summary["reflections"])
        self.assertTrue(json.dumps(c.match_summary, ensure_ascii=False))

    def test_each_bot_style_is_legal_and_error_cases(self):
        rng = random.Random(848)
        for hand in range(90):
            s = core.HandState()
            s.new_match(1000, seed=hand)
            for action_index in range(200):
                if s.hand_over:
                    break
                if s.next_to_act is None:
                    if s.street == "river":
                        s.resolve_showdown()
                    else:
                        s.advance_street()
                    continue
                s.ensure_dealt(s.street)
                p = s.next_to_act
                reply = bots.decide(s, p, bots.STYLES[hand % 3], rng)
                self.assertIn(reply["action"], s.legal_actions(p)["actions"])
                s.apply_action(p, reply["action"], reply["to_cents"])
                self.assertEqual(2000, sum(s.stacks.values()) + s.pot_cents)
            self.assertTrue(s.hand_over)
        empty = core.HandState()
        with self.assertRaises(ValueError):
            bots.decide(empty, "AI_A")
        empty.new_match()
        with self.assertRaises(ValueError):
            bots.decide(empty, "AI_A")


class MatchUiTests(unittest.TestCase):
    def test_empty_demo_settings_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QtCore.QSettings(str(Path(directory) / "prefs.ini"), QtCore.QSettings.Format.IniFormat)
            with patch("core.load_dotenv", return_value={}), patch("app_shell.QtCore.QSettings", return_value=settings):
                window = main.MainWindow()
                try:
                    self.assertEqual([], window.shell.timeline.events)
                    formats = window.shell.dialog.format_controls
                    formats.format.setCurrentIndex(1)
                    formats.hands.setValue(3)
                    self.assertEqual("3", window._collect_env_data()["MATCH_HANDS"])
                    self.assertEqual("fixed", window._collect_env_data()["MATCH_FORMAT"])
                    with patch("core.save_dotenv"):
                        window.on_save_env()
                    self.assertEqual(MatchRules("fixed", 3), window.controller.rules)
                    window.shell.level_notice("盲注升至第 2 级")
                    self.assertEqual("info", window.error_bar.property("tone"))
                    self.assertFalse(window.error_bar.isHidden())
                    window.error_bar.hide()
                    window.a_name.setText("未保存")
                    window.stack_input.setValue(1234)
                    window.shell.dialog.reject()
                    self.assertEqual(1234, window.stack_input.value())
                    self.assertNotEqual("未保存", window.a_name.text())
                    controls = window.provider_controls["A"]
                    controls.provider.setCurrentText("内置机器人")
                    self.assertEqual(bots.BASE_URL, window.a_base.text())
                    self.assertFalse(window.a_key.isEnabled())
                    self.assertTrue(window.a_model.count())
                    self.assertFalse(window.a_model.isEditable())
                    with patch("core.save_dotenv") as save:
                        window.shell.start_demo()
                        save.assert_not_called()
                    window.timer.stop()
                    self.assertTrue(window.shell.configured)
                    self.assertTrue(bots.configured(window.controller.profile["AI_A"]))
                    window.controller.pause()
                    window.controller._invalidate_requests()
                    window.controller.rules = MatchRules("fixed", 1)
                    window.controller.start_new_match(10000, 50, 100)
                    window.controller.execute_action("fold", None)
                    summary = window.shell.summary
                    self.assertTrue(summary.isVisible())
                    path = str(Path(directory) / "summary.json")
                    with patch("match_widgets.QtWidgets.QFileDialog.getSaveFileName", return_value=(path, "")):
                        summary.export()
                    data = json.loads(Path(path).read_text())
                    self.assertEqual(1, data["hands"])
                    self.assertNotIn("api_key", json.dumps(data))
                    with patch("match_widgets.QtWidgets.QFileDialog.getSaveFileName", return_value=("", "")):
                        summary.export()
                    with patch("match_widgets.QtWidgets.QFileDialog.getSaveFileName", return_value=("/nonexistent/summary.json", "")):
                        summary.export()
                    self.assertFalse(window.error_bar.isHidden())
                finally:
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_avatar_initials(self):
        for name, expected in (("选手 A", "A"), ("选手 B", "B"), ("AI_A", "A"), ("李白", "李"), ("DeepSeek", "D"), ("", "?")):
            self.assertEqual(expected, theme.initials(name))
