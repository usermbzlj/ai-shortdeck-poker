import html

from PySide6 import QtCore, QtGui, QtWidgets

import core
import theme


SPEEDS = {"慢": (1800, 7), "标准": (800, 3), "快": (300, 1.5), "极速": (40, 0)}
FILTERS = {"全部": None, "动作": "action", "推理": "reasoning", "喊话": "speech", "解说": "commentary"}
KINDS = {"action": "动作", "reasoning": "内心 OS", "speech": "喊话",
         "commentary": "解说", "monologue": "选手独白", "warning": "提示",
         "system": "牌桌动态", "hand": "新的一手"}


def icon(kind, color=theme.TEXT):
    pixmap = QtGui.QPixmap(40, 40)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(color), 3, QtCore.Qt.PenStyle.SolidLine,
                       QtCore.Qt.PenCapStyle.RoundCap))
    p.setBrush(QtGui.QColor(color))
    if kind in ("play", "step", "next"):
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(12, 9), QtCore.QPointF(12, 31), QtCore.QPointF(29, 20)]))
        if kind != "play":
            p.drawLine(32, 10, 32, 30)
    elif kind == "pause":
        p.drawRoundedRect(11, 9, 5, 22, 1, 1)
        p.drawRoundedRect(24, 9, 5, 22, 1, 1)
    elif kind == "mic":
        p.drawRoundedRect(16, 5, 8, 19, 4, 4)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(10, 12, 20, 19, 180 * 16, 180 * 16)
        p.drawLine(20, 31, 20, 36)
        p.drawLine(14, 36, 26, 36)
    elif kind == "settings":
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(10, 10, 20, 20)
        p.drawEllipse(17, 17, 6, 6)
        for angle in range(0, 360, 45):
            p.save()
            p.translate(20, 20)
            p.rotate(angle)
            p.drawLine(0, -15, 0, -11)
            p.restore()
    else:
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(20, 4), QtCore.QPointF(34, 20),
                                       QtCore.QPointF(20, 36), QtCore.QPointF(6, 20)]))
    p.end()
    return QtGui.QIcon(pixmap)


def button(text, callback, glyph=None, variant="secondary", tip=None):
    b = QtWidgets.QPushButton(text)
    b.setProperty("variant", variant)
    if glyph:
        b.setIcon(icon(glyph, "#211a09" if variant == "primary" else theme.TEXT))
        b.setIconSize(QtCore.QSize(18, 18))
    b.setToolTip(tip or text)
    b.clicked.connect(callback)
    return b


def avatar(name, color):
    pixmap = QtGui.QPixmap(72, 72)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(color), 3))
    p.setBrush(QtGui.QColor(theme.ELEVATED))
    p.drawEllipse(3, 3, 66, 66)
    p.setFont(theme.paint_font(29, True))
    p.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, name[:1])
    p.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap


class Timeline(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = []
        self.filter_name = "全部"
        self.following = True
        self._adding = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        filters = QtWidgets.QHBoxLayout()
        filters.setSpacing(3)
        self.filters = QtWidgets.QButtonGroup(self)
        for name in FILTERS:
            b = button(name, lambda checked=False, n=name: self.set_filter(n), variant="ghost")
            b.setCheckable(True)
            self.filters.addButton(b)
            filters.addWidget(b)
        self.filters.buttons()[0].setChecked(True)
        layout.addLayout(filters)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QtWidgets.QWidget()
        self.cards = QtWidgets.QVBoxLayout(self.body)
        self.cards.setContentsMargins(2, 8, 2, 8)
        self.cards.setSpacing(10)
        self.cards.addStretch()
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll)
        self.new_messages = button("↓ 新消息", self.jump_to_latest, variant="primary")
        self.new_messages.hide()
        layout.addWidget(self.new_messages)
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._range_changed)

    def _range_changed(self, minimum, maximum):
        if self.following and not self._adding:
            QtCore.QTimer.singleShot(0, self, self._follow_if_live)

    def _follow_if_live(self):
        if self.following:
            self.jump_to_latest()

    def _scrolled(self, value):
        if not self._adding:
            self.following = value >= self.scroll.verticalScrollBar().maximum() - 12
            if self.following:
                self.new_messages.hide()

    def jump_to_latest(self):
        self.following = True
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
        self.new_messages.hide()

    def set_filter(self, name):
        self.following = True
        self.filter_name = name
        for b in self.filters.buttons():
            b.setChecked(b.text() == name)
        while self.cards.count() > 1:
            self.cards.takeAt(0).widget().deleteLater()
        for event in self.events:
            if self.matches(event):
                self._append_card(event)
        QtCore.QTimer.singleShot(0, self, self._follow_if_live)

    def matches(self, event):
        return FILTERS[self.filter_name] in (None, event["type"])

    def add_event(self, event):
        self.events.append(dict(event))
        if len(self.events) > 500:
            removed = self.events.pop(0)
            if self.matches(removed):
                self.cards.takeAt(0).widget().deleteLater()
        if not self.matches(event):
            return
        self._adding = True
        self._append_card(event)
        def settle():
            if self.following:
                self.jump_to_latest()
            else:
                self.new_messages.show()
            self._adding = False

        QtCore.QTimer.singleShot(0, self, settle)

    def _append_card(self, event):
        kind = event["type"]
        card = QtWidgets.QFrame()
        card.setObjectName("eventCard")
        card.setProperty("kind", kind)
        box = QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(13, 10, 13, 12)
        color = theme.PLAYER_A if event.get("player") == "AI_A" else theme.PLAYER_B
        if not event.get("player"):
            color = theme.GOLD if kind == "commentary" else theme.SECONDARY
        heading = QtWidgets.QHBoxLayout()
        dot = QtWidgets.QLabel("●")
        dot.setFixedWidth(15)
        palette = dot.palette()
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(color))
        dot.setPalette(palette)
        dot.setProperty("player", "A" if event.get("player") == "AI_A" else "B" if event.get("player") else "neutral")
        heading.addWidget(dot)
        title = QtWidgets.QLabel(event.get("name") or KINDS.get(kind, "动态"))
        title.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        title.setProperty("role", "eventTitle")
        heading.addWidget(title, 1)
        tag = QtWidgets.QLabel(KINDS.get(kind, "动态"))
        tag.setProperty("role", "hint")
        tag.setVisible(bool(event.get("name")))
        if kind == "commentary":
            dot.setPixmap(icon("mic", theme.GOLD).pixmap(15, 18))
        heading.addWidget(tag)
        box.addLayout(heading)
        text = str(event["text"])
        if kind == "speech":
            text = "“" + text + "”"
        if event.get("amount") is not None:
            text += "  $" + core.dollars_from_cents(event["amount"])
        body = QtWidgets.QLabel(text)
        body.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(body)
        self.cards.insertWidget(self.cards.count() - 1, card)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, w):
        super().__init__(w)
        self.w = w
        self.setWindowTitle("设置 · 短牌竞技场")
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.resize(980, 800)
        root = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("偏好与配置")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        row = QtWidgets.QHBoxLayout()
        self.nav = QtWidgets.QListWidget()
        self.nav.addItems(["选手 A", "选手 B", "解说员", "对局", "外观", "高级"])
        self.nav.setFixedWidth(160)
        self.stack = QtWidgets.QStackedWidget()
        row.addWidget(self.nav)
        row.addWidget(self.stack, 1)
        root.addLayout(row, 1)
        source = w.tab_settings.findChild(QtWidgets.QScrollArea).widget()
        groups = source.findChildren(QtWidgets.QGroupBox, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
        a, b, c, advanced = groups
        a.setTitle("选手 A · 模型与风格")
        b.setTitle("选手 B · 模型与风格")
        pages = [a, b, c]
        match = QtWidgets.QGroupBox("对局偏好")
        match_form = QtWidgets.QFormLayout(match)
        appearance = QtWidgets.QGroupBox("牌桌外观")
        appearance_form = QtWidgets.QFormLayout(appearance)
        for widget, form in ((w.temp, match_form), (w.four_color_deck, appearance_form),
                             (w.show_equity, appearance_form), (w.reduce_motion, appearance_form)):
            taken = advanced.layout().takeRow(widget)
            if taken.labelItem:
                label = taken.labelItem.widget()
                form.addRow(label, widget)
            else:
                form.addRow(widget)
        pages.extend([match, appearance, advanced])
        for group in pages:
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            host = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(host)
            layout.addWidget(group)
            layout.addStretch()
            scroll.setWidget(host)
            self.stack.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        footer = QtWidgets.QHBoxLayout()
        footer.addWidget(QtWidgets.QLabel("配置保存在本机 · API Key 不会出现在直播间"))
        footer.addStretch()
        footer.addWidget(button("取消", self.reject, variant="ghost"))
        footer.addWidget(button("保存", self.save, variant="primary"))
        root.addLayout(footer)
        w.btn_save_env.hide()
        self.rejected.connect(self.reload_forms)

    def reload_forms(self):
        controls = (self.w.stack_input, self.w.sb_input, self.w.bb_input)
        values = [widget.value() for widget in controls]
        self.w._load_env_to_ui()
        for widget, value in zip(controls, values):
            widget.setValue(value)

    def save(self):
        try:
            self.w.on_save_env()
        except (OSError, ValueError) as error:
            self.w.on_error(str(error))
            return
        self.accept()

    def show_settings(self):
        self.reload_forms()
        self.open()


class AppShell(QtCore.QObject):
    def __init__(self, w):
        super().__init__(w)
        self.w = w
        self.settings = QtCore.QSettings("ShortDeck", "Arena")
        host = QtWidgets.QWidget()
        host.setObjectName("workspace")
        root = QtWidgets.QVBoxLayout(host)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(12)
        bar = QtWidgets.QFrame()
        bar.setObjectName("appBar")
        bar_layout = QtWidgets.QVBoxLayout(bar)
        header = QtWidgets.QHBoxLayout()
        brand = QtWidgets.QLabel()
        brand.setPixmap(icon("brand", theme.GOLD).pixmap(32, 32))
        header.addWidget(brand)
        title = QtWidgets.QLabel("短牌竞技场")
        title.setObjectName("brandTitle")
        header.addWidget(title)
        self.score = QtWidgets.QLabel()
        self.score.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.score.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Preferred)
        self.avatar_a = QtWidgets.QLabel()
        self.avatar_b = QtWidgets.QLabel()
        header.addStretch()
        header.addWidget(self.avatar_a)
        header.addWidget(self.score)
        header.addWidget(self.avatar_b)
        header.addStretch()
        self.hand = QtWidgets.QLabel()
        header.addWidget(self.hand)
        header.addWidget(button("设置", self.show_settings, "settings", "ghost"))
        bar_layout.addLayout(header)
        transport = QtWidgets.QHBoxLayout()
        self.play = button("开始", w.on_auto_start, "play", "primary", "开始 / 继续 · Space")
        self.pause_button = button("暂停", self.pause, "pause", tip="暂停，保留正在进行的决策 · Space")
        self.step = button("单步", self.single_step, "step", tip="执行一次 AI 行动或推进一街 · N")
        self.next_hand = button("下一手", w.on_next_hand, "next")
        for b in (self.play, self.pause_button, self.step, self.next_hand):
            transport.addWidget(b)
        transport.addStretch()
        transport.addWidget(QtWidgets.QLabel("节奏"))
        self.speed = QtWidgets.QButtonGroup(self)
        for name in SPEEDS:
            b = button(name, lambda checked=False, n=name: self.set_speed(n), variant="ghost")
            b.setCheckable(True)
            self.speed.addButton(b)
            transport.addWidget(b)
        transport.addSpacing(16)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["观赛", "导演"])
        self.mode.setParent(host)
        self.mode.hide()
        self.mode_buttons = QtWidgets.QButtonGroup(self)
        for name in ("观赛", "导演"):
            b = button(name, lambda checked=False, n=name: self.mode.setCurrentText(n), variant="ghost")
            b.setCheckable(True)
            self.mode_buttons.addButton(b)
            transport.addWidget(b)
        bar_layout.addLayout(transport)
        root.addWidget(bar)
        self.splitter = QtWidgets.QSplitter()
        self.drawer = w.tab_game
        source = self.drawer.findChild(QtWidgets.QScrollArea).widget()
        self.director_tools = QtWidgets.QToolBox()
        groups = source.findChildren(QtWidgets.QGroupBox, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
        for group, title in zip(groups, ("比赛设置", "指定牌面", "手动操作", "自动选项")):
            page = QtWidgets.QScrollArea()
            page.setWidgetResizable(True)
            content = QtWidgets.QWidget()
            page_layout = QtWidgets.QVBoxLayout(content)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addWidget(group)
            page_layout.addStretch()
            page.setWidget(content)
            self.director_tools.addItem(page, title)
        old_scroll = self.drawer.layout().takeAt(0).widget()
        old_scroll.hide()
        self.drawer.layout().addWidget(self.director_tools)
        self.director_tools.setCurrentIndex(2)
        self.drawer.setMinimumWidth(290)
        self.drawer.setMaximumWidth(400)
        self.splitter.addWidget(self.drawer)
        self.stage = QtWidgets.QStackedWidget()
        self.stage.addWidget(w.board_panel)
        self.empty = QtWidgets.QWidget()
        empty_layout = QtWidgets.QVBoxLayout(self.empty)
        empty_layout.addStretch()
        card = QtWidgets.QFrame()
        card.setObjectName("emptyCard")
        card.setMaximumWidth(580)
        card.setMinimumWidth(440)
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(40, 40, 40, 40)
        mark = QtWidgets.QLabel()
        mark.setPixmap(icon("brand", theme.GOLD).pixmap(64, 64))
        mark.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(mark)
        for text, role in (("欢迎来到短牌竞技场", "pageTitle"),
                           ("让两位 AI 选手，展开一场有性格的对决", "eventTitle"),
                           ("先为选手 A 与 B 选择模型并测试连接。\n配置只需一次，随后即可坐下来观赛。", "hint")):
            label = QtWidgets.QLabel(text)
            label.setObjectName(role)
            label.setProperty("role", role)
            label.setWordWrap(True)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(label)
        card_layout.addSpacing(15)
        card_layout.addWidget(button("去配置", self.show_settings, "settings", "primary"))
        empty_layout.addWidget(card, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.stage.addWidget(self.empty)
        self.splitter.addWidget(self.stage)
        sidebar = QtWidgets.QWidget()
        sidebar.setMinimumWidth(295)
        sidebar.setMaximumWidth(440)
        side_layout = QtWidgets.QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_title = QtWidgets.QLabel("直播间   ·   LIVE")
        side_title.setObjectName("sectionTitle")
        side_layout.addWidget(side_title)
        self.sidebar_tabs = QtWidgets.QTabWidget()
        self.timeline = Timeline()
        self.sidebar_tabs.addTab(self.timeline, "实时动态")
        self.sidebar_tabs.addTab(w.log, "原始日志")
        side_layout.addWidget(self.sidebar_tabs)
        self.splitter.addWidget(sidebar)
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter, 1)
        toast = w.error_bar
        toast.setMaximumWidth(850)
        toast.setParent(host)
        self.host = host
        self.bar = bar
        host.installEventFilter(self)
        toast.installEventFilter(self)
        w.error_details_button.toggled.connect(lambda: QtCore.QTimer.singleShot(0, self, self.position_toast))
        w.setCentralWidget(host)
        self.dialog = SettingsDialog(w)
        self.mode.currentTextChanged.connect(self.set_mode)
        self.add_sizing()
        self.add_shortcuts()
        self.set_speed(self.settings.value("speed", "标准"))
        self.mode.setCurrentText(self.settings.value("mode", "观赛"))
        self.set_mode(self.mode.currentText())
        self.timeline.set_filter(self.settings.value("filter", "全部") if self.settings.value("filter", "全部") in FILTERS else "全部")
        if self.settings.value("geometry") is not None:
            w.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("splitter") is not None:
            self.splitter.restoreState(self.settings.value("splitter"))
        else:
            self.splitter.setSizes([310, 1000, 330])
        self.configured = False

    def set_configured(self, configured):
        self.configured = configured
        self.stage.setCurrentIndex(0 if configured else 1)
        self.play.setEnabled(configured)
        self.step.setEnabled(configured)

    def set_mode(self, mode):
        for b in self.mode_buttons.buttons():
            b.setChecked(b.text() == mode)
        director = mode == "导演"
        self.drawer.setVisible(director)
        self.sidebar_tabs.setTabVisible(1, director)
        if not director:
            self.sidebar_tabs.setCurrentIndex(0)

    def set_speed(self, name):
        if name not in SPEEDS:
            name = "标准"
        for b in self.speed.buttons():
            b.setChecked(b.text() == name)
        delay, interval = SPEEDS[name]
        self.w.delay_ms.setValue(delay)
        self.w.hand_interval_spin.setValue(interval)
        self.w.controller.skip_action_commentary = name == "极速"
        self.speed_name = name

    def pause(self):
        self.w.timer.stop()
        self.w.controller.pause()

    def single_step(self):
        if not self.w._update_config_hint():
            return
        self.w.timer.stop()
        self.w.controller.single_step()

    def toggle(self):
        if self.w.controller.auto_running:
            self.pause()
        else:
            self.w.on_auto_start()

    def show_settings(self):
        self.dialog.show_settings()

    def position_toast(self):
        toast = self.w.error_bar
        toast.setFixedWidth(min(760, self.host.width() - 48))
        toast.adjustSize()
        toast.move((self.host.width() - toast.width()) // 2, self.bar.height() + 24)
        toast.raise_()

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show):
            if obj == self.host or obj == self.w.error_bar:
                QtCore.QTimer.singleShot(0, self, self.position_toast)
        return super().eventFilter(obj, event)

    def update_state(self, vm):
        a, b = (html.escape(vm.player_names[p]) for p in ("AI_A", "AI_B"))
        self.avatar_a.setPixmap(avatar(vm.player_names["AI_A"], theme.PLAYER_A))
        self.avatar_b.setPixmap(avatar(vm.player_names["AI_B"], theme.PLAYER_B))
        lead = vm.stacks_cents["AI_A"] - vm.stacks_cents["AI_B"]
        delta = core.dollars_from_cents(abs(lead))
        self.score.setText(f'<span style="color:{theme.PLAYER_A}">● {a} · {vm.hands_won.get("AI_A", 0)} 胜</span>'
                           f'   vs   <span style="color:{theme.PLAYER_B}">● {b} · {vm.hands_won.get("AI_B", 0)} 胜</span>'
                           f'   ｜   {"平筹码" if lead == 0 else (a if lead > 0 else b) + " 领先 $" + delta}')
        self.hand.setText(f"第 {vm.hand_id} 手")
        self.play.setEnabled(not vm.auto_state.running and getattr(self, "configured", False))
        self.pause_button.setEnabled(vm.auto_state.running or vm.thinking)
        self.step.setEnabled(not vm.thinking and not vm.auto_state.running and getattr(self, "configured", False))
        self.next_hand.setEnabled(vm.hand_over and not vm.thinking)
        legal = vm.legal
        self.sizing_slider.blockSignals(True)
        self.sizing_slider.setRange(round(self.w.to_spin.minimum() * 100), round(self.w.to_spin.maximum() * 100))
        self.sizing_slider.setValue(round(self.w.to_spin.value() * 100))
        self.sizing_slider.blockSignals(False)
        enabled = (legal.can_bet or legal.can_raise) and not vm.thinking
        self.sizing_slider.setEnabled(enabled)
        for btn in self.sizing_buttons:
            btn.setEnabled(enabled)

    def add_sizing(self):
        w = self.w
        group = w.to_spin.parentWidget()
        layout = group.layout()
        quick = QtWidgets.QGridLayout()
        quick.setSpacing(3)
        self.sizing_buttons = []
        for text, ratio in (("1/3 池", 1/3), ("1/2 池", .5), ("2/3 池", 2/3), ("满池", 1), ("2x", 2), ("全押", None)):
            b = button(text, lambda checked=False, r=ratio: self.size_bet(r), variant="ghost")
            quick.addWidget(b, len(self.sizing_buttons) // 3, len(self.sizing_buttons) % 3)
            self.sizing_buttons.append(b)
        layout.addLayout(quick, 4, 0, 1, 3)
        self.sizing_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        label = layout.itemAtPosition(1, 0).widget()
        label.setText("目标金额 ($)")
        label.setWordWrap(True)
        layout.addWidget(self.sizing_slider, 5, 0, 1, 3)
        self.sizing_slider.valueChanged.connect(lambda v: w.to_spin.setValue(v / 100))
        w.to_spin.valueChanged.connect(lambda v: self.sizing_slider.setValue(round(v * 100)))

    def size_bet(self, ratio):
        vm = self.w.vm
        if not vm or not vm.next_to_act:
            return
        legal = vm.legal
        current = vm.contributed_street_cents.get(vm.next_to_act, 0)
        target = legal.max_to_cents if ratio is None else (
            2 * max(current + legal.to_call_cents, self.w.controller.state.bb_cents) if ratio == 2 else
            current + legal.to_call_cents + round((vm.pot_cents + legal.to_call_cents) * ratio))
        self.w.to_spin.setValue(target / 100)

    def add_shortcuts(self):
        w = self.w
        bindings = [("F", w.btn_fold), ("C", None), ("R", w.btn_raise), ("A", w.btn_allin)]
        for key, btn in bindings:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), w)
            shortcut.activated.connect(lambda b=btn: self.manual_shortcut(b))
            if btn:
                btn.setToolTip(btn.toolTip() + " · " + key)
        for btn in (w.btn_check, w.btn_call):
            btn.setToolTip(btn.toolTip() + " · C")
        for key, callback in (("Space", self.toggle), ("N", self.single_step)):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), w)
            shortcut.activated.connect(callback)

    def manual_shortcut(self, btn):
        if self.mode.currentText() != "导演":
            return
        if btn is None:
            btn = self.w.btn_check if self.w.btn_check.isEnabled() else self.w.btn_call
        if btn.isEnabled():
            btn.click()

    def save_state(self):
        self.settings.setValue("geometry", self.w.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("mode", self.mode.currentText())
        self.settings.setValue("speed", self.speed_name)
        self.settings.setValue("filter", self.timeline.filter_name)
