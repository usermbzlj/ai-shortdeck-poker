from PySide6 import QtCore, QtGui, QtWidgets

import core
import theme


class HumanDock(QtWidgets.QFrame):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.vm = None
        self.turn_key = None
        self.setObjectName("humanDock")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 10, 18, 12)
        root.setSpacing(7)
        self.caption = QtWidgets.QLabel("等待你的回合")
        self.caption.setObjectName("humanCaption")
        root.addWidget(self.caption)
        actions = QtWidgets.QHBoxLayout()
        self.fold = QtWidgets.QPushButton("弃牌 · F")
        self.fold.setProperty("variant", "danger")
        self.call = QtWidgets.QPushButton("过牌 · C")
        self.call.setProperty("variant", "primary")
        self.raise_button = QtWidgets.QPushButton("加注 · R")
        self.raise_button.setProperty("variant", "secondary")
        self.amount = QtWidgets.QDoubleSpinBox()
        self.amount.setPrefix("$")
        self.amount.setDecimals(2)
        self.amount.setSingleStep(1)
        self.amount.setFixedWidth(130)
        self.amount.setToolTip("本街累计投入的目标总额，不是额外加注额")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        for widget in (self.fold, self.call, self.raise_button, self.amount, self.slider):
            actions.addWidget(widget, 1 if widget is self.slider else 0)
        root.addLayout(actions)
        bottom = QtWidgets.QHBoxLayout()
        self.chips = []
        for label, fraction in (("1/3 池", 1/3), ("1/2 池", .5), ("2/3 池", 2/3), ("底池", 1)):
            b = QtWidgets.QPushButton(label)
            b.setProperty("variant", "chip")
            b.clicked.connect(lambda checked=False, ratio=fraction: self.size_pot(ratio))
            self.chips.append(b)
            bottom.addWidget(b)
        self.allin = QtWidgets.QPushButton("全下 · A")
        self.allin.setProperty("variant", "chip")
        self.allin.setToolTip("直接全下（或跟注到全下），快捷键 A")
        self.allin.clicked.connect(self.submit_allin)
        bottom.addWidget(self.allin)
        self.speech = QtWidgets.QLineEdit()
        self.speech.setPlaceholderText("可选喊话… 随动作一起发送")
        self.speech.setMaxLength(200)
        bottom.addWidget(self.speech, 1)
        root.addLayout(bottom)
        self.fold.clicked.connect(lambda: self.submit_action("fold"))
        self.call.clicked.connect(lambda: self.submit_action("check" if self.vm.legal.can_check else "call"))
        self.raise_button.clicked.connect(lambda: self.submit_action("raise" if self.vm.legal.can_raise else "bet", round(self.amount.value() * 100)))
        self.amount.valueChanged.connect(lambda amount: self.slider.setValue(round(amount * 100)))
        self.slider.valueChanged.connect(lambda amount: self.amount.setValue(amount / 100))
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 0)
        shadow.setColor(QtGui.QColor("#55f5c451"))
        self.setGraphicsEffect(shadow)
        self.hide()

    def update_state(self, vm):
        self.vm = vm
        self.setVisible(bool(vm.human_player and not vm.hand_over))
        self.graphicsEffect().setEnabled(vm.human_turn)
        if not vm.human_player:
            self.turn_key = None
            return
        active, legal = vm.human_turn, vm.legal
        self.caption.setText("本手结束 · 可在牌谱复盘" if vm.hand_over else
                             "你的回合 · 不限时 · 对手底牌与推理已隐藏" if active and vm.privacy_active else
                             "你的回合 · 不限时 · 当前为上帝视角" if active else
                             "AI 正在思考，请稍候…" if vm.thinking else "等待 AI 行动 · 点击开始继续")
        self.fold.setEnabled(active and legal.can_fold)
        self.call.setEnabled(active and (legal.can_check or legal.can_call))
        self.call.setText("过牌 · C" if legal.can_check else "跟注 " + core.format_money(legal.to_call_cents) + " · C")
        sizing = active and (legal.can_bet or legal.can_raise)
        self.raise_button.setText("加注到 · R" if legal.can_raise else "下注到 · R")
        self.raise_button.setEnabled(sizing)
        self.amount.setEnabled(sizing)
        self.slider.setEnabled(sizing)
        self.allin.setEnabled(active and legal.can_allin)
        self.speech.setEnabled(active)
        for chip in self.chips:
            chip.setEnabled(sizing)
        key = (getattr(self.window.controller, "match_id", None), vm.hand_id, vm.street,
               vm.next_to_act, vm.pot_cents, tuple(vm.contributed_street_cents.items()),
               legal.min_bet_to_cents, legal.min_raise_to_cents, legal.max_to_cents)
        if active and key != self.turn_key:
            maximum = legal.max_to_cents
            minimum = min((legal.min_raise_to_cents if legal.can_raise else legal.min_bet_to_cents) or maximum, maximum)
            self.slider.setRange(minimum, maximum)
            self.amount.setRange(minimum / 100, maximum / 100)
            self.amount.setValue((legal.suggested_to_cents or minimum) / 100)
            self.turn_key = key

    def size_pot(self, ratio):
        if not self.vm or not self.vm.human_turn:
            return
        vm = self.vm
        current = vm.contributed_street_cents[vm.human_player]
        target = current + vm.legal.to_call_cents + round((vm.pot_cents + vm.legal.to_call_cents) * ratio)
        self.amount.setValue(target / 100)

    def submit_action(self, action, target=None):
        if not self.vm or not self.vm.human_turn:
            return
        try:
            self.window.controller.execute_human_action(action, target, self.speech.text())
            self.speech.clear()
        except core.UserFacingError as error:
            self.window.on_error(str(error))

    def submit_allin(self):
        if self.vm and self.vm.human_turn and self.vm.legal.can_allin:
            self.submit_action(self.vm.legal.allin_action, self.vm.legal.allin_to_cents)

    def shortcut(self, key):
        buttons = {"F": self.fold, "C": self.call, "R": self.raise_button, "A": self.allin}
        button = buttons.get(key)
        if button and button.isEnabled():
            button.click()
