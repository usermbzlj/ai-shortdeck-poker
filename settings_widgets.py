import time

import httpx
from PySide6 import QtCore, QtWidgets

import core
import bots
from providers import PROVIDERS, PERSONAS, infer_provider, sends_thinking


class ModelCombo(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        self.setEditable(True)

    def text(self):
        return self.currentText()

    def setText(self, text):
        self.setEditText(text)


class TemperatureInput(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["跟随全局", "自定义", "不发送"])
        self.value = QtWidgets.QDoubleSpinBox()
        self.value.setRange(0, 2)
        self.value.setSingleStep(0.1)
        self.value.setValue(0.2)
        row.addWidget(self.mode)
        row.addWidget(self.value)
        self.mode.currentIndexChanged.connect(lambda i: self.value.setEnabled(i == 1))
        self.value.setEnabled(False)

    def text(self):
        return ("", str(self.value.value()), "none")[self.mode.currentIndex()]

    def setText(self, text):
        if not text.strip():
            self.mode.setCurrentIndex(0)
        elif text.strip().lower() == "none":
            self.mode.setCurrentIndex(2)
        else:
            try:
                self.value.setValue(float(text))
                self.mode.setCurrentIndex(1)
            except ValueError:
                self.mode.setCurrentIndex(0)


class Probe(QtCore.QThread):
    result = QtCore.Signal(bool, object)

    def __init__(self, values, models, parent):
        super().__init__(parent)
        self.values = values
        self.models = models

    def run(self):
        v = self.values
        try:
            start = time.monotonic()
            if v["base"] == bots.BASE_URL:
                self.result.emit(True, list(bots.STYLES) if self.models else "✓ 内置机器人已就绪 · 无需网络或密钥")
                return
            if self.models:
                base = v["base"].rstrip("/").removesuffix("/chat/completions")
                with httpx.Client(timeout=20) as client:
                    response = client.get(base + "/models", headers={"Authorization": "Bearer " + v["key"]})
                    response.raise_for_status()
                    data = response.json()["data"]
                    names = [item["id"] for item in data if isinstance(item.get("id"), str)]
                    if not names:
                        raise ValueError("模型列表为空")
                    self.result.emit(True, names)
            else:
                core.LLMClient(v["base"], v["key"], v["model"], timeout_s=20).chat(
                    [{"role": "user", "content": "请只回复 OK"}],
                    temperature=v["temperature"], thinking_enabled=v["thinking"],
                    thinking_budget=v["budget"], thinking_param=v["param"])
                self.result.emit(True, f"✓ 延迟 {time.monotonic() - start:.1f}s")
        except Exception as error:
            if isinstance(error, httpx.HTTPStatusError):
                message = f"服务返回 HTTP {error.response.status_code}，请检查地址、密钥和权限"
            elif isinstance(error, httpx.RequestError):
                message = "网络连接失败，请检查地址及网络"
            else:
                message = "请求失败，请检查模型、密钥及参数设置"
                if isinstance(error, core.UserFacingError) and "配置不完整" in str(error):
                    message = "请先填写 URL、Key 和 Model"
            self.result.emit(False, "✗ " + message)


class ProviderControls(QtCore.QObject):
    def __init__(self, window, prefix, form, player=False):
        super().__init__(window)
        self.window = window
        self.prefix = prefix
        self.jobs = []
        self.provider = QtWidgets.QComboBox()
        self.provider.addItems([name for name in PROVIDERS if player or name != "内置机器人"])
        self.provider.setCurrentText("自定义")
        form.insertRow(0, "厂商", self.provider)
        self.param = QtWidgets.QComboBox()
        for label, value in (("自动（按厂商预设）", "auto"), ("发送", "send"), ("不发送", "omit")):
            self.param.addItem(label, value)
        form.addRow("thinking 参数", self.param)
        thinking = getattr(window, prefix + "_thinking")
        budget = getattr(window, prefix + "_thinking_budget")
        thinking.toggled.connect(budget.setEnabled)
        budget.setEnabled(thinking.isChecked())
        self.provider.currentTextChanged.connect(self.select_provider)
        buttons = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        self.fetch = QtWidgets.QPushButton("拉取模型列表")
        self.test = QtWidgets.QPushButton("测试连接")
        self.fetch.setProperty("variant", "ghost")
        self.test.setProperty("variant", "primary")
        row.addWidget(self.fetch)
        row.addWidget(self.test)
        form.addRow(buttons)
        self.result = QtWidgets.QLabel()
        self.result.setWordWrap(True)
        form.addRow(self.result)
        self.fetch.clicked.connect(lambda: self.probe(True))
        self.test.clicked.connect(lambda: self.probe(False))
        if player:
            self.persona_preset = QtWidgets.QComboBox()
            self.persona_preset.addItems(["选择人设预设…", *PERSONAS])
            self.persona = QtWidgets.QPlainTextEdit()
            self.persona.setMaximumHeight(80)
            self.persona.setPlaceholderText("留空使用默认风格")
            self.persona_preset.textActivated.connect(
                lambda name: self.persona.setPlainText(PERSONAS[name]) if name in PERSONAS else None)
            form.addRow("选手人设/风格", self.persona_preset)
            form.addRow(self.persona)

    def widget(self, name):
        return getattr(self.window, self.prefix + "_" + name)

    def select_provider(self, name):
        preset = PROVIDERS[name]
        model = self.widget("model")
        previous = model.text()
        model.clear()
        model.addItems(preset.models)
        if preset.base_url:
            self.widget("base").setText(preset.base_url)
        else:
            model.setText(previous)
        self.local_fields()

    def local_fields(self):
        local = self.provider.currentText() == "内置机器人"
        self.widget("model").setEditable(not local)
        self.widget("key").setPlaceholderText("内置机器人无需 API Key" if local else "")
        for name in ("base", "key", "thinking"):
            self.widget(name).setEnabled(not local)
        if local:
            self.widget("thinking").setChecked(False)

    def load(self, env, key):
        name = env.get(key + "_PROVIDER", infer_provider(env.get(key + "_BASE_URL", "")))
        self.provider.blockSignals(True)
        self.provider.setCurrentText(name if name in PROVIDERS else "自定义")
        self.provider.blockSignals(False)
        model = self.widget("model")
        previous = model.text()
        model.clear()
        model.addItems(PROVIDERS[self.provider.currentText()].models)
        model.setText(previous)
        self.param.setCurrentIndex(max(0, self.param.findData(env.get(key + "_THINKING_PARAM", "auto"))))
        self.local_fields()
        if hasattr(self, "persona"):
            import prompts
            self.persona.setPlainText(env.get(key + "_PERSONA", getattr(prompts, key + "_EXTRA_INSTRUCTIONS")))

    def collect(self, key):
        data = {key + "_PROVIDER": self.provider.currentText(), key + "_THINKING_PARAM": self.param.currentData()}
        if hasattr(self, "persona"):
            data[key + "_PERSONA"] = self.persona.toPlainText()
        return data

    def probe(self, models):
        temp = self.widget("temp")
        raw = temp.text() if isinstance(temp, TemperatureInput) else str(temp.value())
        temperature = self.window.temp.value() if not raw else None if raw == "none" else float(raw)
        values = dict(base=self.widget("base").text().strip(), key=self.widget("key").text().strip(),
                      model=self.widget("model").text().strip(), temperature=temperature,
                      thinking=self.widget("thinking").isChecked(), budget=self.widget("thinking_budget").value(),
                      param=sends_thinking(self.param.currentData(), self.provider.currentText()))
        self.result.setText("正在请求…")
        self.fetch.setEnabled(False)
        self.test.setEnabled(False)
        job = Probe(values, models, self)
        self.jobs.append(job)
        job.result.connect(lambda ok, value: self.complete(models, ok, value))
        job.finished.connect(lambda: self.jobs.remove(job))
        job.finished.connect(job.deleteLater)
        job.start()

    def complete(self, models, ok, value):
        same = self.prefix == "c" and self.window.c_same.isChecked()
        self.fetch.setEnabled(not same)
        self.test.setEnabled(True)
        if models and ok:
            model = self.widget("model")
            previous = model.text()
            model.clear()
            model.addItems(value)
            if previous:
                model.setText(previous)
            self.result.setText(f"✓ 已拉取 {len(value)} 个模型")
        else:
            self.result.setText(value)
