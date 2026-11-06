import json

from PySide6 import QtCore, QtWidgets

import core
from match import FORMATS
from stats_widgets import StackChart


class FormatControls(QtWidgets.QGroupBox):
    def __init__(self):
        super().__init__("赛制 · 下一场生效")
        form = QtWidgets.QFormLayout(self)
        self.format = QtWidgets.QComboBox()
        for name, value in FORMATS.items():
            self.format.addItem(name, value)
        self.hands = QtWidgets.QSpinBox()
        self.hands.setRange(1, 100000)
        self.hands.setValue(50)
        self.interval = QtWidgets.QSpinBox()
        self.interval.setRange(1, 100000)
        self.interval.setValue(10)
        self.duplicate = QtWidgets.QCheckBox("交换座位复赛 · 使用相同牌序，合并两场净收益")
        form.addRow("赛制", self.format)
        form.addRow("固定手数 N", self.hands)
        form.addRow("每 N 手升级盲注 ×1.5", self.interval)
        form.addRow(self.duplicate)
        note = QtWidgets.QLabel("任一方输光会提前结束。复赛按首场手数封顶；若提前输光也会结束。\n手动指定的牌面也会记录在牌序中。")
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        form.addRow(note)
        self.format.currentIndexChanged.connect(self.update_enabled)
        self.update_enabled()

    def update_enabled(self):
        self.hands.setEnabled(self.format.currentData() == "fixed")
        self.interval.setEnabled(self.format.currentData() == "levels")

    def load(self, env):
        self.format.setCurrentIndex(max(0, self.format.findData(env.get("MATCH_FORMAT", "bust"))))
        self.hands.setValue(int(env.get("MATCH_HANDS", "50") or 50))
        self.interval.setValue(int(env.get("BLIND_LEVEL_HANDS", "10") or 10))
        self.duplicate.setChecked(env.get("DUPLICATE_MATCH", "false").lower() == "true")

    def collect(self):
        return dict(MATCH_FORMAT=self.format.currentData(), MATCH_HANDS=str(self.hands.value()),
                    BLIND_LEVEL_HANDS=str(self.interval.value()),
                    DUPLICATE_MATCH=str(self.duplicate.isChecked()).lower())


def player_page(window, prefix, original, controls):
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    source = original.layout()

    def take(widget):
        row = source.takeRow(widget)
        if row.labelItem and row.labelItem.widget():
            row.labelItem.widget().deleteLater()
        return widget

    def section(title):
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        form.setSpacing(12)
        layout.addWidget(box)
        return form

    connection = section("连接")
    connection.addRow("厂商", take(controls.provider))
    if hasattr(window, prefix + "_name"):
        connection.addRow("名称", take(getattr(window, prefix + "_name")))
    if prefix == "c":
        connection.addRow(take(window.c_same))
    for key, title in (("base", "Base URL"), ("key", "API Key")):
        connection.addRow(title, take(getattr(window, prefix + "_" + key)))
    models = QtWidgets.QWidget()
    model_row = QtWidgets.QHBoxLayout(models)
    model_row.setContentsMargins(0, 0, 0, 0)
    model_row.addWidget(take(getattr(window, prefix + "_model")), 1)
    controls.fetch.setParent(models)
    model_row.addWidget(controls.fetch)
    connection.addRow("模型", models)
    footer = QtWidgets.QWidget()
    footer_row = QtWidgets.QHBoxLayout(footer)
    footer_row.setContentsMargins(0, 5, 0, 0)
    footer_row.addWidget(take(controls.result), 1)
    controls.test.setParent(footer)
    footer_row.addWidget(controls.test)
    connection.addRow(footer)
    sampling = section("采样")
    sampling.addRow("温度", take(getattr(window, prefix + "_temp")))
    if prefix != "c":
        sampling.addRow(take(getattr(window, prefix + "_memory")))
    thinking = section("思考")
    thinking.addRow(take(getattr(window, prefix + "_thinking")))
    thinking.addRow("Token 上限", take(getattr(window, prefix + "_thinking_budget")))
    thinking.addRow("thinking 参数", take(controls.param))
    if hasattr(controls, "persona"):
        persona = section("人设")
        persona.addRow("预设风格", take(controls.persona_preset))
        controls.persona.setMinimumHeight(90)
        persona.addRow(take(controls.persona))
    if prefix == "c":
        commentary = section("解说时机")
        for name in ("c_on_action", "c_on_street", "c_on_hand", "c_god_view"):
            commentary.addRow(take(getattr(window, name)))
    original.hide()
    return page


class SummaryDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("赛后总结")
        self.resize(920, 760)
        self.data = None
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        self.title = QtWidgets.QLabel()
        self.title.setObjectName("pageTitle")
        heading = QtWidgets.QLabel("赛后总结")
        heading.setProperty("role", "hint")
        root.addWidget(heading)
        root.addWidget(self.title)
        self.subtitle = QtWidgets.QLabel()
        self.subtitle.setProperty("role", "hint")
        root.addWidget(self.subtitle)
        self.players = QtWidgets.QHBoxLayout()
        root.addLayout(self.players, 1)
        self.columns = {}
        self.charts = {}
        for pid in ("AI_A", "AI_B"):
            box = QtWidgets.QGroupBox()
            col = QtWidgets.QVBoxLayout(box)
            name = QtWidgets.QLabel()
            name.setObjectName("pageTitle")
            name.setProperty("player", "A" if pid == "AI_A" else "B")
            stack = QtWidgets.QLabel()
            stack.setObjectName("summaryStack")
            stats = QtWidgets.QLabel()
            stats.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            stats.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
            reflection = QtWidgets.QTextEdit()
            reflection.setReadOnly(True)
            reflection.setObjectName("summaryReflection")
            reflection.setFixedHeight(90)
            for widget in (name, stack, stats):
                col.addWidget(widget)
            curve_title = QtWidgets.QLabel("筹码轨迹")
            curve_title.setProperty("role", "hint")
            col.addWidget(curve_title)
            chart = StackChart(players=(pid,))
            col.addWidget(chart, 1)
            self.charts[pid] = chart
            col.addWidget(QtWidgets.QLabel("赛后感言"))
            col.addWidget(reflection)
            self.players.addWidget(box, 1)
            self.columns[pid] = (name, stack, stats, reflection)
        self.combined = QtWidgets.QLabel()
        self.combined.setWordWrap(True)
        root.addWidget(self.combined)
        buttons = QtWidgets.QHBoxLayout()
        for text, callback in (("再来一场", self.again), ("交换座位复赛", self.duplicate), ("导出", self.export)):
            b = QtWidgets.QPushButton(text)
            b.setProperty("variant", "primary" if text == "再来一场" else "secondary")
            b.clicked.connect(callback)
            buttons.addWidget(b)
            if text == "交换座位复赛":
                self.duplicate_button = b
        root.addLayout(buttons)

    def update_summary(self, data):
        self.data = data
        names, winner = data["names"], data["winner"]
        self.title.setText(("双场综合 · " if data["duplicate"] else "") + (names[winner] + " 获胜" if winner else "双方战平"))
        self.title.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        count = f'首场 {data["first_leg"]["hands"]} 手 / 复赛 {data["hands"]} 手' if data["duplicate"] else f'完成 {data["hands"]} 手'
        biggest = max(data["biggest_pot_cents"], data["first_leg"]["biggest_pot_cents"] if data["first_leg"] else 0)
        caption = "两场合计统计" if data["duplicate"] else "牌序可随总结导出"
        self.subtitle.setText(f'{count}  ·  最大底池 ${core.dollars_from_cents(biggest)}  ·  {caption}')
        for pid, widgets in self.columns.items():
            name, stack, stats, reflection = widgets
            name.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            name.setText(names[pid])
            stack.setText(core.format_money(data["stacks_cents"][pid]))
            s = data["stats"][pid]
            showdown = f'{s["showdown_win"]:.1%}' if s["showdown_count"] else "—"
            stats.setText(f'VPIP  自愿入池率       {s["vpip"]:.1%}\nPFR  翻牌前加注率       {s["pfr"]:.1%}\n摊牌胜率                     {showdown}\n平均思考                     {s["thinking_seconds"]:.2f}s\n非法输出 / 兜底              {s["invalid_outputs"]} / {s["fallbacks"]}')
            self.charts[pid].set_points(data.get("chip_curve", []))
            reflection.setPlainText(data["reflections"].get(pid, "等待选手的赛后感言…"))
        combined = "  ·  ".join(names[p] + " 净收益 " + core.format_money(data["combined_cents"][p]) for p in names)
        self.combined.setText(("两场合计：" if data["duplicate"] else "本场结算：") + combined)
        self.combined.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.duplicate_button.setEnabled(not data["duplicate"])

    def present(self, data):
        self.update_summary(data)
        self.show()
        self.raise_()

    def again(self):
        self.accept()
        c = self.window.controller
        c.start_new_match(c.state.start_stack_cents, *c._base_blinds)
        self.window.on_auto_start()

    def duplicate(self):
        self.accept()
        self.window.controller.start_duplicate()
        self.window.on_auto_start()

    def export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出赛后总结与牌序", "match_summary.json", "JSON (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as output:
                    json.dump(self.data, output, ensure_ascii=False, indent=2)
            except OSError as error:
                self.window.on_error(str(error))
