import json
import unittest
from unittest.mock import MagicMock, patch

import httpx
from PySide6 import QtCore, QtWidgets

import core
import main
from controller import GameController


class DecisionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.controller = GameController()
        self.controller.start_new_match(10000, 50, 100)
        self.controller._trigger_player_reactions = MagicMock()
        self.controller._trigger_commentary = MagicMock()
        self.controller.active_request_id = 1
        self.player = self.controller.state.next_to_act

    def result(self, content):
        self.controller._handle_llm_result(self.controller.active_request_id, self.player, content, "")

    def test_bad_json_then_good_action_and_counters(self):
        c = self.controller
        with patch("controller.threading.Thread") as thread:
            c.request_ai_decision()
        self.assertEqual(1, c.model_stats[self.player]["decisions"])
        with patch("controller._schedule") as timer:
            self.result("not json")
        self.assertEqual(1, c.model_stats[self.player]["invalid_outputs"])
        self.assertEqual(1, c.model_stats[self.player]["retries"])
        self.assertEqual("assistant", c._decision_messages[-2]["role"])
        self.assertIn("合法动作", c._decision_messages[-1]["content"])
        with patch.object(c, "request_ai_decision") as request:
            timer.call_args.args[1]()
        self.assertIn("not json", request.call_args.args[0][-2]["content"])
        self.result('{"action": "call"}')
        self.assertNotEqual(self.player, c.state.next_to_act)
        self.assertEqual(0, c._consecutive_failures)

    def test_clamp_and_bet_raise_mapping(self):
        c = self.controller
        minimum = c.state.legal_actions(self.player)["min_raise_to_cents"]
        self.result('{"action":"bet", "to_cents":0}')
        self.assertEqual(minimum, c.state.contributed_street[self.player])
        self.assertEqual(1, c.model_stats[self.player]["clamps"])

    def test_retry_then_clamp_when_disabled_and_exhausted(self):
        c = self.controller
        c.clamp_sizing = False
        c.max_decision_retries = 1
        with patch("controller._schedule"):
            self.result('{"action":"raise","to_cents":999999}')
        self.assertIn("超出最大值", c._decision_messages[-1]["content"])
        self.result('{"action":"raise","to_cents":999999}')
        self.assertEqual(1, c.model_stats[self.player]["clamps"])
        self.assertEqual(2, c.model_stats[self.player]["invalid_outputs"])

    def test_exhaustion_falls_back_to_fold(self):
        c = self.controller
        logs = []
        c.logAppended.connect(lambda s: logs.append(s))
        with patch("controller._schedule"):
            for _ in range(3):
                self.result("bad JSON")
        self.assertTrue(c.state.hand_over)
        self.assertEqual(1, c.model_stats[self.player]["fallbacks"])
        self.assertEqual(2, c.model_stats[self.player]["retries"])
        self.assertTrue(any("🛟 兜底动作" in line for line in logs))
        self.assertEqual(0, c._consecutive_failures)

    def test_call_maps_to_check_and_check_fallback(self):
        c = self.controller
        c.state.apply_action(self.player, "call", None)
        self.player = c.state.next_to_act
        self.result('{"action":"call"}')
        self.assertEqual("过牌", c.state.action_history[-1].split()[-1])

    def test_check_facing_bet_is_invalid(self):
        c = self.controller
        with patch("controller._schedule"):
            self.result('{"action":"check"}')
        self.assertEqual(1, c.model_stats[self.player]["retries"])
        self.assertIn("action=check", c._decision_messages[-1]["content"])

    def test_fallback_check_and_view_model_snapshot(self):
        c = self.controller
        c.state.apply_action(self.player, "call", None)
        self.player = c.state.next_to_act
        c.max_decision_retries = 0
        snapshots = []
        c.viewModelChanged.connect(lambda v: snapshots.append(v))
        self.result("bad")
        self.assertEqual(1, snapshots[-1].model_stats[self.player]["fallbacks"])
        c.model_stats[self.player]["fallbacks"] += 1
        self.assertEqual(1, snapshots[-1].model_stats[self.player]["fallbacks"])

    def test_network_backoff_then_circuit_breaker_and_stale_timer(self):
        c = self.controller
        c.auto_running = True
        c._decision_messages = [{"role": "user", "content": "test"}]
        for delay in (1000, 2000, 4000):
            with patch("controller._schedule") as timer:
                c._handle_llm_error(1, self.player, "timeout")
            self.assertEqual(delay, timer.call_args.args[0])
            self.assertTrue(c.thinking)
            self.assertEqual(0, c._consecutive_failures)
        c._handle_llm_error(1, self.player, "timeout")
        self.assertEqual(1, c._consecutive_failures)
        c._invalidate_requests()
        with patch.object(c, "request_ai_decision") as request:
            timer.call_args.args[1]()
            request.assert_not_called()


class FriendlyErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_http_errors(self):
        for status, detail, message in ((401, "bad key", "API Key 无效或无权限"),
                                        (403, "", "API Key 无效或无权限"),
                                        (402, "", "账户余额不足"),
                                        (400, "insufficient balance", "账户余额不足"),
                                        (404, "", "模型或 API 路径不存在"),
                                        (429, "", "触发限流"),
                                        (503, "", "服务端错误")):
            with self.subTest(status=status):
                client = MagicMock()
                client.__enter__.return_value = client
                client.post.return_value = httpx.Response(status, text=detail)
                with patch("core.httpx.Client", return_value=client):
                    with self.assertRaisesRegex(core.UserFacingError, message):
                        core.LLMClient("https://example.com/v1", "key", "model").chat([])

    def test_timeout(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.side_effect = httpx.ReadTimeout("slow")
        with patch("core.httpx.Client", return_value=client):
            with self.assertRaisesRegex(core.UserFacingError, r"请求超时\(12s\)"):
                core.LLMClient("https://example.com", "key", "model", 12).chat([])

    def test_nonmodal_notification_and_settings(self):
        with patch("core.load_dotenv", return_value={}):
            window = main.MainWindow()
        with patch.object(QtWidgets.QMessageBox, "warning") as popup:
            window.on_error("错误摘要\n详细信息")
            popup.assert_not_called()
        self.assertFalse(window.error_bar.isHidden())
        window.error_details_button.setChecked(True)
        self.assertFalse(window.error_details.isHidden())
        self.assertEqual("错误摘要\n详细信息", window.error_details.toPlainText())
        self.assertFalse(window.error_timer.isActive())
        data = window._collect_env_data()
        self.assertEqual("2", data["MAX_DECISION_RETRIES"])
        self.assertEqual("", data["AI_TIMEOUT_S"])
        self.assertEqual("true", data["CLAMP_OUT_OF_RANGE"])
        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
