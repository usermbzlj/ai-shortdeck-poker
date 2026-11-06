import tempfile
import unittest
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets

from controller import GameController
import main


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.c = GameController()
        self.c.start_new_match(10000, 50, 100)
        self.events = []
        self.c.eventRaised.connect(self.events.append)

    def tearDown(self):
        self.c.deleteLater()

    def test_pause_retains_and_applies_inflight_result(self):
        c = self.c
        with patch("controller.threading.Thread"):
            c.request_ai_decision()
        req, player = c.active_request_id, c.state.next_to_act
        c.set_auto_running(True)
        c.pause()
        self.assertEqual(req, c.active_request_id)
        self.assertTrue(c.thinking)
        c._handle_llm_result(req, player, '{"action":"call","analysis":"范围很强","trash_talk":"来吧"}', "")
        self.assertNotEqual(player, c.state.next_to_act)
        self.assertFalse(c.auto_running)
        self.assertEqual(["reasoning", "speech", "action"], [e["type"] for e in self.events])
        self.assertNotIn("AI_A", self.events[-1]["name"])

    def test_single_step_schedules_only_one_decision(self):
        c = self.c
        with patch("controller.threading.Thread") as worker:
            c.single_step()
            req, player = c.active_request_id, c.state.next_to_act
            c.single_step()
            c.auto_tick()
            worker.assert_called_once()
        c._handle_llm_result(req, player, '{"action":"call"}', "")
        self.assertFalse(c.auto_running)
        self.assertFalse(c.thinking)

    def test_single_step_advances_only_one_street_and_stop_still_invalidates(self):
        c = self.c
        c.state.ensure_dealt("preflop")
        c.execute_action("call", None)
        c.execute_action("check", None)
        c.single_step()
        self.assertEqual("flop", c.state.street)
        self.assertFalse(c.auto_running)
        self.assertFalse(c.thinking)
        c.active_request_id = 4
        c.thinking = True
        c.set_auto_running(False)
        self.assertEqual(0, c.active_request_id)
        self.assertFalse(c.thinking)

    def test_failure_and_empty_commentary_events(self):
        c = self.c
        c._handle_comment_result("好一手牌")
        c._handle_comment_error("网络中断")
        c._handle_reaction_result("AI_A", "独白", "")
        self.assertEqual(["commentary", "warning"], [e["type"] for e in self.events])
        c._handle_reaction_result("AI_B", "独白", "下手更谨慎")
        self.assertEqual("monologue", self.events[-1]["type"])

    def test_fastest_skips_action_commentary_only(self):
        c = self.c
        c.commentator.base_url = "https://example.test/v1"
        c.commentator.api_key = "test"
        c.commentator.model = "test"
        c.skip_action_commentary = True
        with patch("controller.threading.Thread") as worker:
            c._trigger_commentary("加注", is_action=True)
            worker.assert_not_called()
            c._trigger_commentary("翻牌")
            worker.return_value.start.assert_called_once()


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(self.temp.name + "/shell.ini", QtCore.QSettings.Format.IniFormat)
        self.settings_patch = patch("app_shell.QtCore.QSettings", return_value=self.settings)
        self.settings_patch.start()
        self.env_patch = patch("core.load_dotenv", return_value={})
        self.env_patch.start()
        self.w = main.MainWindow()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.env_patch.stop()
        self.settings_patch.stop()
        self.temp.cleanup()

    def test_empty_mode_settings_navigation_and_cancel(self):
        shell = self.w.shell
        self.assertEqual(shell.empty, shell.stage.currentWidget())
        self.assertTrue(shell.drawer.isHidden())
        shell.mode.setCurrentText("导演")
        self.assertFalse(shell.drawer.isHidden())
        self.assertTrue(shell.sidebar_tabs.isTabVisible(1))
        shell.dialog.show_settings()
        shell.dialog.nav.setCurrentRow(4)
        self.assertEqual(4, shell.dialog.stack.currentIndex())
        self.w.a_name.setText("未保存")
        shell.dialog.reject()
        self.assertNotEqual("未保存", self.w.a_name.text())

    def test_filter_persistence_speed_and_slider(self):
        shell = self.w.shell
        c = self.w.controller
        c.emit_event("action", "加注", "AI_A", 500)
        c.emit_event("reasoning", "观察范围", "AI_B")
        shell.timeline.set_filter("动作")
        self.assertEqual(2, shell.timeline.cards.count())
        shell.set_speed("极速")
        self.assertTrue(c.skip_action_commentary)
        self.assertEqual(40, self.w.delay_ms.value())
        shell.set_speed("标准")
        self.assertFalse(c.skip_action_commentary)
        shell.mode.setCurrentText("导演")
        shell.size_bet(.5)
        self.assertEqual(round(self.w.to_spin.value() * 100), shell.sizing_slider.value())
        shell.save_state()
        self.assertEqual("动作", self.settings.value("filter"))
        self.assertEqual("导演", self.settings.value("mode"))
        self.assertEqual("标准", self.settings.value("speed"))

    def test_new_match_cancel_preserves_state(self):
        state = self.w.controller.state
        with patch("main.QtWidgets.QMessageBox.question", return_value=QtWidgets.QMessageBox.StandardButton.No):
            self.w.on_new_match()
        self.assertIs(state, self.w.controller.state)

    def test_save_settings_and_report_write_error_without_closing(self):
        dialog = self.w.shell.dialog
        dialog.show_settings()
        self.w.reduce_motion.setChecked(True)
        with patch("core.save_dotenv") as save:
            dialog.save()
        self.assertEqual("true", save.call_args.args[1]["REDUCE_MOTION"])
        self.assertTrue(self.w.controller.reduce_motion)
        self.assertFalse(dialog.isVisible())
        dialog.show_settings()
        with patch("core.save_dotenv", side_effect=OSError("无法写入配置")):
            dialog.save()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(self.w.error_bar.isHidden())
        dialog.reject()

    def test_restore_preferences_and_twice_current_bet_sizing(self):
        shell = self.w.shell
        self.w.controller.execute_action("raise", 1500)
        shell.size_bet(2)
        self.assertEqual(3000, round(self.w.to_spin.value() * 100))
        shell.mode.setCurrentText("导演")
        shell.set_speed("快")
        shell.timeline.set_filter("喊话")
        shell.save_state()
        other = main.MainWindow()
        try:
            self.assertEqual("导演", other.shell.mode.currentText())
            self.assertEqual("快", other.shell.speed_name)
            self.assertEqual("喊话", other.shell.timeline.filter_name)
        finally:
            other.close()
            other.deleteLater()

    def test_new_messages_do_not_steal_scroll_position(self):
        timeline = self.w.shell.timeline
        timeline.resize(320, 240)
        self.w.resize(1280, 800)
        self.w.show()
        for i in range(20):
            self.w.controller.emit_event("reasoning", "观察范围 " * 10, "AI_A")
        self.app.processEvents()
        self.app.processEvents()
        timeline.jump_to_latest()
        bar = timeline.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0)
        self.w.controller.emit_event("speech", "新的喊话", "AI_B")
        self.app.processEvents()
        self.assertEqual(0, bar.value())
        self.assertFalse(timeline.new_messages.isHidden())
        timeline.jump_to_latest()
        self.assertEqual(bar.maximum(), bar.value())
