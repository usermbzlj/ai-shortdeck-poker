import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import httpx
from PySide6 import QtWidgets

import core
import main
import providers
from controller import GameController
from settings_widgets import Probe, TemperatureInput


class ConfigurationTests(unittest.TestCase):
    def test_presets_and_thinking_modes(self):
        self.assertEqual(11, len(providers.PROVIDERS))
        for name, preset in providers.PROVIDERS.items():
            self.assertEqual(preset.thinking, providers.sends_thinking("auto", name))
            self.assertTrue(providers.sends_thinking("send", name))
            self.assertFalse(providers.sends_thinking("omit", name))
        self.assertEqual("OpenAI", providers.infer_provider("https://api.openai.com"))
        self.assertTrue(providers.sends_thinking("auto", "自定义"))

    def test_thinking_payload_and_errors(self):
        response = httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = response
        with patch("core.httpx.Client", return_value=client):
            llm = core.LLMClient("https://example.com/v1", "key", "model")
            for send, enabled in ((False, False), (False, True), (True, False), (True, True)):
                llm.chat([], thinking_enabled=enabled, thinking_param=send)
                payload = client.post.call_args.kwargs["json"]
                self.assertEqual(send, "thinking" in payload)
                if send:
                    self.assertEqual("enabled" if enabled else "disabled", payload["thinking"]["type"])
            client.post.return_value = httpx.Response(401, text="unauthorized")
            with self.assertRaises(core.UserFacingError):
                llm.chat([])
        with self.assertRaises(core.UserFacingError):
            core.LLMClient("", "", "").chat([])

    def test_persona_normal_empty_and_prompt_fallback(self):
        controller = GameController()
        controller.start_new_match(10000, 50, 100)
        controller.load_env({"A_PERSONA": "理性\n不冲动", "B_PERSONA": ""})
        self.assertIn("═══ 你的风格 ═══\n理性\n不冲动", controller._build_llm_messages("AI_A")[0]["content"])
        self.assertNotIn("═══ 你的风格 ═══", controller._build_llm_messages("AI_B")[0]["content"])
        with patch("prompts.A_EXTRA_INSTRUCTIONS", "默认风格"):
            controller.load_env({})
            self.assertIn("默认风格", controller._build_llm_messages("AI_A")[0]["content"])

    def test_env_roundtrip(self):
        data = {"A_PERSONA": '第一行\n"引号" \\n = # 第二行\n',
                "B_PERSONA": "", "A_PROVIDER": "OpenAI", "B_PROVIDER": "自定义",
                "A_THINKING_PARAM": "omit", "B_THINKING_PARAM": "send",
                "COMMENTATOR_THINKING_PARAM": "auto", "COMMENTATOR_SAME_AS_A": "true",
                "A_TEMPERATURE": "", "B_TEMPERATURE": "none", "A_API_KEY": "legacy-key"}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, ".env")
            self.assertEqual({}, core.load_dotenv(path))
            core.save_dotenv(path, data)
            self.assertEqual(data, core.load_dotenv(path))

    def test_profile_provider_auto_and_commentator_link(self):
        controller = GameController()
        controller.load_env({"A_BASE_URL": "https://api.openai.com/v1", "A_API_KEY": "key",
                             "A_MODEL": "test", "COMMENTATOR_SAME_AS_A": "true"})
        self.assertFalse(controller.profile["AI_A"].thinking_param)
        self.assertEqual("test", controller.commentator.model)
        self.assertFalse(controller.commentator.thinking_param)


class SettingsWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_unsaved_form_presets_link_and_first_run(self):
        with patch("core.load_dotenv", return_value={}):
            window = main.MainWindow()
        self.assertEqual(window.shell.empty, window.shell.stage.currentWidget())
        self.assertFalse(window.shell.play.isEnabled())
        controls = window.provider_controls["A"]
        controls.provider.setCurrentText("OpenAI")
        self.assertEqual("https://api.openai.com/v1", window.a_base.text())
        self.assertGreater(window.a_model.count(), 1)
        window.c_same.setChecked(True)
        window.a_model.setText("unsaved-model")
        self.assertEqual("unsaved-model", window.c_model.text())
        self.assertFalse(window.c_model.isEnabled())
        self.assertFalse(window.a_thinking_budget.isEnabled())
        window.a_thinking.setChecked(True)
        self.assertTrue(window.a_thinking_budget.isEnabled())
        controls.persona.setPlainText("风格\n第二行")
        data = window._collect_env_data()
        self.assertEqual("风格\n第二行", data["A_PERSONA"])
        self.assertEqual("", data["A_TEMPERATURE"])
        for raw in ("", "none", "0.75"):
            field = TemperatureInput()
            field.setText(raw)
            self.assertEqual(raw, field.text())
        with patch.object(QtWidgets.QMessageBox, "critical") as popup:
            window.on_auto_start()
            popup.assert_not_called()
            self.assertFalse(window.timer.isActive())
        window.close()

    def test_probe_models_success_empty_error_and_chat(self):
        values = dict(base="https://example.com/v1", key="secret", model="test",
                      temperature=None, thinking=False, budget=8000, param=False)
        for payload, expected in (({"data": [{"id": "model-a"}]}, True), ({"data": []}, False)):
            client = MagicMock()
            client.__enter__.return_value = client
            client.get.return_value = httpx.Response(200, json=payload, request=httpx.Request("GET", values["base"]))
            probe = Probe(values, True, None)
            results = []
            probe.result.connect(lambda ok, result: results.append((ok, result)))
            with patch("settings_widgets.httpx.Client", return_value=client):
                probe.run()
            self.assertEqual(expected, results[0][0])
        for error in (None, core.UserFacingError("API HTTP 错误：401 secret")):
            results = []
            probe = Probe(values, False, None)
            probe.result.connect(lambda ok, result: results.append((ok, result)))
            with patch("core.LLMClient.chat", side_effect=error, return_value={"content": "OK"}) as chat:
                probe.run()
            self.assertEqual(error is None, results[0][0])
            self.assertNotIn("secret", str(results))
            self.assertFalse(chat.call_args.kwargs["thinking_param"])
