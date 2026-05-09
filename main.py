import logging
import os
import sys
import threading


def _reconfigure_stream_utf8(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


# Windows 下强制 stdout/stderr 使用 UTF-8，避免 emoji 和中文导致编码崩溃
if sys.platform == "win32":
    _reconfigure_stream_utf8(sys.stdout)
    _reconfigure_stream_utf8(sys.stderr)

from PySide6 import QtCore, QtGui, QtWidgets

import core
from controller import AppViewModel, GameController, PlayerID
from server import WebSocketManager

log = logging.getLogger("poker.ui")

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

SUIT_CN_SHORT = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
SUIT_COLOR = {"s": "#1a1a1a", "h": "#d40000", "d": "#d40000", "c": "#1a1a1a"}

_CARD_W, _CARD_H = 48, 62

_CARD_FACE_CSS = (
    f"background:#fffff5; border:2px solid #aaa; border-radius:6px;"
    f"font:bold 13px 'Microsoft YaHei','Segoe UI';"
    f"min-width:{_CARD_W}px; max-width:{_CARD_W}px;"
    f"min-height:{_CARD_H}px; max-height:{_CARD_H}px;"
)
_CARD_EMPTY_CSS = (
    f"background:#1a4d1a; border:2px dashed #3a7a3a; border-radius:6px;"
    f"color:#3a7a3a; font:12px 'Microsoft YaHei';"
    f"min-width:{_CARD_W}px; max-width:{_CARD_W}px;"
    f"min-height:{_CARD_H}px; max-height:{_CARD_H}px;"
)


class CardLabel(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.set_card("")

    def set_card(self, text: str) -> None:
        if not text or len(text) < 2:
            self.setText("")
            self.setStyleSheet(_CARD_EMPTY_CSS)
            return
        rank = text[0].upper()
        suit = text[1].lower()
        symbol = SUIT_CN_SHORT.get(suit, "?")
        color = SUIT_COLOR.get(suit, "#000")
        self.setText(f"{rank}\n{symbol}")
        self.setStyleSheet(_CARD_FACE_CSS + f" color:{color};")


class BoardPanel(QtWidgets.QFrame):
    """牌桌可视化面板：显示双方手牌、公共牌、筹码、底池等。"""

    def __init__(self):
        super().__init__()
        self.setObjectName("boardPanel")
        self.setStyleSheet(
            "#boardPanel {"
            "  background: qlineargradient(y1:0, y2:1, stop:0 #0d5016, stop:1 #0a3d0a);"
            "  border-radius: 12px; border: 3px solid #1a6b1a;"
            "}"
        )
        self.setMinimumHeight(270)
        self._build()

    def _build(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(14, 10, 14, 10)

        self._a = self._make_player_row()
        root.addLayout(self._a["layout"])
        root.addWidget(self._sep())

        mid = QtWidgets.QHBoxLayout()
        info_col = QtWidgets.QVBoxLayout()
        self.lbl_pot = QtWidgets.QLabel("底池: $0.00")
        self.lbl_pot.setStyleSheet("color:#ffd700; font:bold 16px; background:transparent;")
        self.lbl_street = QtWidgets.QLabel("PREFLOP")
        self.lbl_street.setStyleSheet("color:#aaffaa; font:bold 12px; background:transparent;")
        self.lbl_hand = QtWidgets.QLabel("Hand #0")
        self.lbl_hand.setStyleSheet("color:#88aa88; font:11px; background:transparent;")
        info_col.addWidget(self.lbl_pot)
        info_col.addWidget(self.lbl_street)
        info_col.addWidget(self.lbl_hand)
        mid.addLayout(info_col)
        mid.addStretch(1)

        self.community_cards: list[CardLabel] = []
        for _ in range(5):
            c = CardLabel()
            self.community_cards.append(c)
            mid.addWidget(c)
        mid.addStretch(1)
        root.addLayout(mid)

        root.addWidget(self._sep())
        self._b = self._make_player_row()
        root.addLayout(self._b["layout"])

    def _make_player_row(self) -> dict:
        layout = QtWidgets.QHBoxLayout()
        transparent = "background:transparent;"

        indicator = QtWidgets.QLabel("●")
        indicator.setFixedWidth(22)
        indicator.setStyleSheet(f"color:#333; font:20px; {transparent}")
        indicator.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        name_lbl = QtWidgets.QLabel("AI")
        name_lbl.setStyleSheet(f"color:white; font:bold 14px; {transparent}")
        name_lbl.setMinimumWidth(90)

        btn_badge = QtWidgets.QLabel("")
        btn_badge.setFixedSize(26, 26)
        btn_badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        btn_badge.setStyleSheet(transparent)

        cards: list[CardLabel] = []
        for _ in range(2):
            c = CardLabel()
            cards.append(c)

        layout.addWidget(indicator)
        layout.addWidget(name_lbl)
        layout.addWidget(btn_badge)
        for c in cards:
            layout.addWidget(c)
        layout.addStretch(1)

        stack_lbl = QtWidgets.QLabel("$0.00")
        stack_lbl.setStyleSheet(f"color:#ffffff; font:bold 14px; {transparent}")
        stack_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)

        bet_lbl = QtWidgets.QLabel("")
        bet_lbl.setStyleSheet(f"color:#ffcc00; font:12px; {transparent}")
        bet_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        bet_lbl.setMinimumWidth(90)

        layout.addWidget(stack_lbl)
        layout.addWidget(bet_lbl)

        return {
            "layout": layout, "indicator": indicator, "name": name_lbl,
            "button": btn_badge, "cards": cards, "stack": stack_lbl, "bet": bet_lbl,
        }

    @staticmethod
    def _sep() -> QtWidgets.QFrame:
        s = QtWidgets.QFrame()
        s.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        s.setStyleSheet("background:#2a7a2a; max-height:1px;")
        return s

    def update_state(self, vm: AppViewModel) -> None:
        na = vm.player_names.get("AI_A", "AI_A")
        nb = vm.player_names.get("AI_B", "AI_B")
        self._update_player(self._a, "AI_A", na, vm)
        self._update_player(self._b, "AI_B", nb, vm)

        for i, cl in enumerate(self.community_cards):
            cl.set_card(vm.board_cards[i] if i < len(vm.board_cards) else "")

        self.lbl_pot.setText(f"底池: ${core.dollars_from_cents(vm.pot_cents)}")
        self.lbl_street.setText(vm.street.upper())
        self.lbl_hand.setText(f"Hand #{vm.hand_id}")

    @staticmethod
    def _update_player(row: dict, pid: PlayerID, name: str, vm: AppViewModel) -> None:
        t = "background:transparent;"
        row["name"].setText(name)

        hole = vm.hole_cards.get(pid, ["", ""])
        for i, cl in enumerate(row["cards"]):
            cl.set_card(hole[i] if i < len(hole) else "")

        stack = vm.stacks_cents.get(pid, 0)
        row["stack"].setText(f"💰 ${core.dollars_from_cents(stack)}")

        bet = vm.contributed_street_cents.get(pid, 0)
        row["bet"].setText(f"下注: ${core.dollars_from_cents(bet)}" if bet > 0 else "")

        is_active = vm.next_to_act == pid
        row["indicator"].setStyleSheet(
            f"color:{'#00ff00' if is_active else '#333'}; font:20px; {t}"
        )

        if vm.button == pid:
            row["button"].setText("D")
            row["button"].setStyleSheet(
                "background:#ffd700; color:#333; font:bold 12px;"
                "border-radius:13px; min-width:26px; min-height:26px;"
            )
        else:
            row["button"].setText("")
            row["button"].setStyleSheet(t)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("短牌德州 LLM 对战引擎")
        self.resize(1400, 850)

        self.controller = GameController()
        self.controller.viewModelChanged.connect(self.on_vm_changed)
        self.controller.logAppended.connect(self.append_log)
        self.controller.commentaryAppended.connect(self.append_commentary)
        self.controller.errorRaised.connect(self.on_error)

        self.vm: AppViewModel | None = None

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.on_auto_tick)

        self._build_ui()
        self._load_env_to_ui()
        self.controller.load_env(core.load_dotenv(ENV_PATH))
        self.on_new_match()

    # ═══════════════════════════ UI 构建 ═══════════════════════════

    def _build_ui(self) -> None:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # ── 左侧：对局 + 设置 tabs ──
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)

        tabs = QtWidgets.QTabWidget()
        left_layout.addWidget(tabs, 1)

        self.tab_game = QtWidgets.QWidget()
        self.tab_settings = QtWidgets.QWidget()
        tabs.addTab(self.tab_game, "对局")
        tabs.addTab(self.tab_settings, "设置")

        self._build_game_tab()
        self._build_settings_tab()

        splitter.addWidget(left)

        # ── 右侧：牌桌 + 日志 + 解说 + 历史 ──
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.board_panel = BoardPanel()

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QtGui.QFont("Consolas", 10))

        self.commentary = QtWidgets.QTextEdit()
        self.commentary.setReadOnly(True)
        self.commentary.setFont(QtGui.QFont("Microsoft YaHei", 10))
        self.commentary.setStyleSheet("QTextEdit { background-color: #1a1a2e; color: #e0e0ff; }")
        self.commentary.setPlaceholderText("解说员尚未配置或未开启...")

        self.history = QtWidgets.QListWidget()

        right_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        right_split.addWidget(self.board_panel)
        right_split.addWidget(self._make_labeled_group("📋 对局日志", self.log))
        right_split.addWidget(self._make_labeled_group("🎙️ 解说席", self.commentary))
        right_split.addWidget(self._make_labeled_group("📜 行动历史", self.history))
        right_split.setStretchFactor(0, 2)
        right_split.setStretchFactor(1, 3)
        right_split.setStretchFactor(2, 2)
        right_split.setStretchFactor(3, 1)

        right_layout.addWidget(right_split, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)

    def _make_labeled_group(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(widget)
        return box

    # ───────────────────── 对局 Tab ─────────────────────

    def _build_game_tab(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.tab_game)

        _HINT = "color:#888; font:11px;"
        _BTN_PRIMARY = (
            "QPushButton { background:#2563eb; color:white; font:bold 13px; padding:6px 12px;"
            "border-radius:4px; } QPushButton:disabled { background:#555; color:#999; }"
        )
        _BTN_DANGER = (
            "QPushButton { background:#dc2626; color:white; font:bold 13px; padding:6px 12px;"
            "border-radius:4px; } QPushButton:disabled { background:#555; color:#999; }"
        )
        _BTN_SUCCESS = (
            "QPushButton { background:#16a34a; color:white; font:bold 13px; padding:6px 12px;"
            "border-radius:4px; } QPushButton:disabled { background:#555; color:#999; }"
        )
        _BTN_WARN = (
            "QPushButton { background:#d97706; color:white; font:bold 13px; padding:6px 12px;"
            "border-radius:4px; } QPushButton:disabled { background:#555; color:#999; }"
        )
        _BTN_NORMAL = (
            "QPushButton { font:13px; padding:6px 10px; border-radius:4px; }"
            "QPushButton:disabled { color:#999; }"
        )

        # ── 对局控制 ──
        match_box = QtWidgets.QGroupBox("对局控制")
        form = QtWidgets.QFormLayout(match_box)

        self.stack_input = QtWidgets.QDoubleSpinBox()
        self.stack_input.setRange(0.01, 1_000_000)
        self.stack_input.setDecimals(2)
        self.stack_input.setValue(1000.0)

        self.sb_input = QtWidgets.QDoubleSpinBox()
        self.sb_input.setRange(0.01, 1_000_000)
        self.sb_input.setDecimals(2)
        self.sb_input.setValue(2.5)

        self.bb_input = QtWidgets.QDoubleSpinBox()
        self.bb_input.setRange(0.01, 1_000_000)
        self.bb_input.setDecimals(2)
        self.bb_input.setValue(5.0)

        form.addRow("初始筹码 ($)", self.stack_input)
        form.addRow("小盲注 ($)", self.sb_input)
        form.addRow("大盲注 ($)", self.bb_input)

        row_start = QtWidgets.QHBoxLayout()
        self.btn_new_match = QtWidgets.QPushButton("开始新比赛")
        self.btn_new_match.setStyleSheet(_BTN_PRIMARY)
        self.btn_new_match.setToolTip("重置双方筹码，开始一场全新比赛")
        self.btn_next_hand = QtWidgets.QPushButton("开始下一手")
        self.btn_next_hand.setStyleSheet(_BTN_SUCCESS)
        self.btn_next_hand.setToolTip("当前手牌结束后，点此发下一手牌")
        row_start.addWidget(self.btn_new_match)
        row_start.addWidget(self.btn_next_hand)
        form.addRow(row_start)

        row_advance = QtWidgets.QHBoxLayout()
        self.btn_next_street = QtWidgets.QPushButton("发下一轮公共牌")
        self.btn_next_street.setStyleSheet(_BTN_WARN)
        self.btn_next_street.setToolTip("当前轮行动结束后，翻开下一轮公共牌（翻牌→转牌→河牌）")
        self.btn_showdown = QtWidgets.QPushButton("摊牌结算")
        self.btn_showdown.setStyleSheet(_BTN_DANGER)
        self.btn_showdown.setToolTip("河牌轮行动结束后，双方亮牌比大小")
        row_advance.addWidget(self.btn_next_street)
        row_advance.addWidget(self.btn_showdown)
        form.addRow(row_advance)

        self.btn_new_match.clicked.connect(self.on_new_match)
        self.btn_next_hand.clicked.connect(self.on_next_hand)
        self.btn_next_street.clicked.connect(self.on_next_street)
        self.btn_showdown.clicked.connect(self.on_showdown)

        layout.addWidget(match_box)

        # ── 手动指定牌面（可选） ──
        cards_box = QtWidgets.QGroupBox("手动指定牌面（可选，留空则随机发牌）")
        cards_layout = QtWidgets.QGridLayout(cards_box)

        self._card_codes = [""] + core.all_short_deck_texts()

        def make_combo():
            cb = QtWidgets.QComboBox()
            for code in self._card_codes:
                display = core.card_to_chinese(code) if code else "(随机)"
                cb.addItem(display, userData=code)
            cb.setEditable(False)
            cb.setMinimumWidth(80)
            return cb

        self.a1 = make_combo()
        self.a2 = make_combo()
        self.b1 = make_combo()
        self.b2 = make_combo()
        self.f1 = make_combo()
        self.f2 = make_combo()
        self.f3 = make_combo()
        self.t1 = make_combo()
        self.r1 = make_combo()

        self.lbl_a_cards = QtWidgets.QLabel("AI_A 底牌")
        self.lbl_b_cards = QtWidgets.QLabel("AI_B 底牌")

        cards_layout.addWidget(self.lbl_a_cards, 0, 0)
        cards_layout.addWidget(self.a1, 0, 1)
        cards_layout.addWidget(self.a2, 0, 2)

        cards_layout.addWidget(self.lbl_b_cards, 1, 0)
        cards_layout.addWidget(self.b1, 1, 1)
        cards_layout.addWidget(self.b2, 1, 2)

        cards_layout.addWidget(QtWidgets.QLabel("公共牌"), 2, 0)
        cards_layout.addWidget(self.f1, 2, 1)
        cards_layout.addWidget(self.f2, 2, 2)
        cards_layout.addWidget(self.f3, 2, 3)
        cards_layout.addWidget(self.t1, 2, 4)
        cards_layout.addWidget(self.r1, 2, 5)

        self.btn_lock_cards = QtWidgets.QPushButton("确认指定")
        self.btn_lock_cards.setToolTip("将上面选择的牌锁定到本局")
        self.btn_ensure_dealt = QtWidgets.QPushButton("随机补齐缺牌")
        self.btn_ensure_dealt.setToolTip("未指定的位置自动随机发牌")
        self.btn_lock_cards.setStyleSheet(_BTN_NORMAL)
        self.btn_ensure_dealt.setStyleSheet(_BTN_NORMAL)
        cards_layout.addWidget(self.btn_lock_cards, 3, 0, 1, 3)
        cards_layout.addWidget(self.btn_ensure_dealt, 3, 3, 1, 3)

        self.btn_lock_cards.clicked.connect(self.on_lock_cards)
        self.btn_ensure_dealt.clicked.connect(self.on_ensure_dealt)

        layout.addWidget(cards_box)

        # ── 手动操作（替 AI 做决策） ──
        actions_box = QtWidgets.QGroupBox("手动操作（替当前 AI 做决策）")
        actions_layout = QtWidgets.QGridLayout(actions_box)

        self.lbl_to_call = QtWidgets.QLabel("需跟注: $0.00")
        self.lbl_to_call.setStyleSheet("font:bold 13px;")
        actions_layout.addWidget(self.lbl_to_call, 0, 0, 1, 3)

        self.to_spin = QtWidgets.QDoubleSpinBox()
        self.to_spin.setRange(0.0, 1_000_000.0)
        self.to_spin.setDecimals(2)
        self.to_spin.setSingleStep(0.5)
        lbl_to = QtWidgets.QLabel("下注/加注目标金额 ($)")
        lbl_to.setToolTip("Bet/Raise 时，填入你希望「下注到」的总金额")
        actions_layout.addWidget(lbl_to, 1, 0)
        actions_layout.addWidget(self.to_spin, 1, 1, 1, 2)

        self.btn_fold = QtWidgets.QPushButton("弃牌")
        self.btn_check = QtWidgets.QPushButton("过牌")
        self.btn_call = QtWidgets.QPushButton("跟注")
        self.btn_bet = QtWidgets.QPushButton("下注")
        self.btn_raise = QtWidgets.QPushButton("加注")

        self.btn_fold.setToolTip("放弃本手牌，认输")
        self.btn_check.setToolTip("不加注，轮到对手行动")
        self.btn_call.setToolTip("跟上对手的下注金额")
        self.btn_bet.setToolTip("率先下注（无人下注时可用）")
        self.btn_raise.setToolTip("在对手下注基础上加注")

        _BTN_ALLIN = (
            "QPushButton { background:#7c3aed; color:white; font:bold 13px; padding:6px 12px;"
            "border-radius:4px; } QPushButton:disabled { background:#555; color:#999; }"
        )

        self.btn_allin = QtWidgets.QPushButton("全押 (All-In)")
        self.btn_allin.setToolTip("押上全部筹码")

        self.btn_fold.setStyleSheet(_BTN_DANGER)
        self.btn_check.setStyleSheet(_BTN_NORMAL)
        self.btn_call.setStyleSheet(_BTN_SUCCESS)
        self.btn_bet.setStyleSheet(_BTN_WARN)
        self.btn_raise.setStyleSheet(_BTN_WARN)
        self.btn_allin.setStyleSheet(_BTN_ALLIN)

        actions_layout.addWidget(self.btn_fold, 2, 0)
        actions_layout.addWidget(self.btn_check, 2, 1)
        actions_layout.addWidget(self.btn_call, 2, 2)
        actions_layout.addWidget(self.btn_bet, 3, 0)
        actions_layout.addWidget(self.btn_raise, 3, 1)
        actions_layout.addWidget(self.btn_allin, 3, 2)

        self.btn_fold.clicked.connect(lambda: self.on_action("fold"))
        self.btn_check.clicked.connect(lambda: self.on_action("check"))
        self.btn_call.clicked.connect(lambda: self.on_action("call"))
        self.btn_bet.clicked.connect(lambda: self.on_action("bet"))
        self.btn_raise.clicked.connect(lambda: self.on_action("raise"))
        self.btn_allin.clicked.connect(self.on_allin)

        layout.addWidget(actions_box)

        # ── 自动对局 ──
        auto_box = QtWidgets.QGroupBox("自动对局（让 AI 自动思考和行动）")
        auto_layout = QtWidgets.QFormLayout(auto_box)

        self.chk_auto_fill = QtWidgets.QCheckBox("自动随机补齐缺牌")
        self.chk_auto_fill.setChecked(True)
        self.chk_auto_fill.setToolTip("AI 需要行动前，自动发出尚未发的牌")
        self.chk_auto_advance = QtWidgets.QCheckBox("自动发公共牌并推进（全自动）")
        self.chk_auto_advance.setChecked(True)
        self.chk_auto_advance.setToolTip("每轮行动结束后自动翻下一轮公共牌，一直打到摊牌")

        self.delay_ms = QtWidgets.QSpinBox()
        self.delay_ms.setRange(0, 60000)
        self.delay_ms.setValue(500)
        self.delay_ms.setToolTip("两步行动之间的等待时间，方便观察过程")

        self.hand_interval_spin = QtWidgets.QDoubleSpinBox()
        self.hand_interval_spin.setRange(0.0, 30.0)
        self.hand_interval_spin.setSingleStep(0.5)
        self.hand_interval_spin.setDecimals(1)
        self.hand_interval_spin.setValue(3.0)
        self.hand_interval_spin.setSuffix(" 秒")
        self.hand_interval_spin.setToolTip("一手牌结束后，等待多久再自动开始下一手")

        row2 = QtWidgets.QHBoxLayout()
        self.btn_auto_start = QtWidgets.QPushButton("▶ 开始自动对局")
        self.btn_auto_stop = QtWidgets.QPushButton("⏹ 停止")
        self.btn_auto_start.setStyleSheet(_BTN_PRIMARY)
        self.btn_auto_stop.setStyleSheet(_BTN_DANGER)
        row2.addWidget(self.btn_auto_start)
        row2.addWidget(self.btn_auto_stop)

        auto_layout.addRow(self.chk_auto_fill)
        auto_layout.addRow(self.chk_auto_advance)
        auto_layout.addRow("每步延迟 (毫秒)", self.delay_ms)
        auto_layout.addRow("手牌间隔", self.hand_interval_spin)
        auto_layout.addRow(row2)

        self.btn_auto_start.clicked.connect(self.on_auto_start)
        self.btn_auto_stop.clicked.connect(self.on_auto_stop)
        self.delay_ms.valueChanged.connect(self.on_delay_changed)
        self.hand_interval_spin.valueChanged.connect(self.on_hand_interval_changed)
        self.chk_auto_fill.toggled.connect(self.on_auto_options_changed)
        self.chk_auto_advance.toggled.connect(self.on_auto_options_changed)

        layout.addWidget(auto_box)
        layout.addStretch(1)

    # ───────────────────── 设置 Tab ─────────────────────

    def _build_settings_tab(self) -> None:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        # ── AI_A ──
        a_box = QtWidgets.QGroupBox("AI_A")
        a_form = QtWidgets.QFormLayout(a_box)
        self.a_name = QtWidgets.QLineEdit()
        self.a_name.setPlaceholderText("显示名称，如 DeepSeek")
        self.a_base = QtWidgets.QLineEdit()
        self.a_key = QtWidgets.QLineEdit()
        self.a_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.a_model = QtWidgets.QLineEdit()
        self.a_thinking = QtWidgets.QCheckBox("开启深度思考 (thinking)")
        self.a_thinking_budget = QtWidgets.QSpinBox()
        self.a_thinking_budget.setRange(1000, 100000)
        self.a_thinking_budget.setSingleStep(1000)
        self.a_thinking_budget.setValue(8000)
        self.a_memory = QtWidgets.QCheckBox("启用本手牌记忆")
        self.a_memory.setChecked(True)
        self.a_temp = QtWidgets.QLineEdit()
        self.a_temp.setPlaceholderText("留空=用全局温度，none=不发送")
        a_form.addRow("名称", self.a_name)
        a_form.addRow("Base URL", self.a_base)
        a_form.addRow("API Key", self.a_key)
        a_form.addRow("Model", self.a_model)
        a_form.addRow("Temperature", self.a_temp)
        a_form.addRow(self.a_thinking)
        a_form.addRow("思考 Token 上限", self.a_thinking_budget)
        a_form.addRow(self.a_memory)

        # ── AI_B ──
        b_box = QtWidgets.QGroupBox("AI_B")
        b_form = QtWidgets.QFormLayout(b_box)
        self.b_name = QtWidgets.QLineEdit()
        self.b_name.setPlaceholderText("显示名称，如 GLM")
        self.b_base = QtWidgets.QLineEdit()
        self.b_key = QtWidgets.QLineEdit()
        self.b_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.b_model = QtWidgets.QLineEdit()
        self.b_thinking = QtWidgets.QCheckBox("开启深度思考 (thinking)")
        self.b_thinking_budget = QtWidgets.QSpinBox()
        self.b_thinking_budget.setRange(1000, 100000)
        self.b_thinking_budget.setSingleStep(1000)
        self.b_thinking_budget.setValue(8000)
        self.b_memory = QtWidgets.QCheckBox("启用本手牌记忆")
        self.b_memory.setChecked(True)
        self.b_temp = QtWidgets.QLineEdit()
        self.b_temp.setPlaceholderText("留空=用全局温度，none=不发送")
        b_form.addRow("名称", self.b_name)
        b_form.addRow("Base URL", self.b_base)
        b_form.addRow("API Key", self.b_key)
        b_form.addRow("Model", self.b_model)
        b_form.addRow("Temperature", self.b_temp)
        b_form.addRow(self.b_thinking)
        b_form.addRow("思考 Token 上限", self.b_thinking_budget)
        b_form.addRow(self.b_memory)

        # ── 解说员 ──
        c_box = QtWidgets.QGroupBox("🎙️ 解说员")
        c_form = QtWidgets.QFormLayout(c_box)
        self.c_base = QtWidgets.QLineEdit()
        self.c_key = QtWidgets.QLineEdit()
        self.c_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.c_model = QtWidgets.QLineEdit()
        self.c_temp = QtWidgets.QDoubleSpinBox()
        self.c_temp.setRange(0.0, 2.0)
        self.c_temp.setSingleStep(0.1)
        self.c_temp.setDecimals(2)
        self.c_temp.setValue(0.7)
        self.c_thinking = QtWidgets.QCheckBox("开启深度思考 (thinking)")
        self.c_thinking_budget = QtWidgets.QSpinBox()
        self.c_thinking_budget.setRange(1000, 100000)
        self.c_thinking_budget.setSingleStep(1000)
        self.c_thinking_budget.setValue(8000)
        self.c_on_action = QtWidgets.QCheckBox("每个动作后解说")
        self.c_on_action.setChecked(True)
        self.c_on_street = QtWidgets.QCheckBox("每街结束后解说")
        self.c_on_street.setChecked(True)
        self.c_on_hand = QtWidgets.QCheckBox("每手结束后解说")
        self.c_on_hand.setChecked(True)
        self.c_god_view = QtWidgets.QCheckBox("上帝视角（看双方底牌）")
        self.c_god_view.setChecked(True)

        c_form.addRow("Base URL", self.c_base)
        c_form.addRow("API Key", self.c_key)
        c_form.addRow("Model", self.c_model)
        c_form.addRow("Temperature", self.c_temp)
        c_form.addRow(self.c_thinking)
        c_form.addRow("思考 Token 上限", self.c_thinking_budget)
        c_form.addRow(self.c_on_action)
        c_form.addRow(self.c_on_street)
        c_form.addRow(self.c_on_hand)
        c_form.addRow(self.c_god_view)

        # ── 通用 ──
        temp_box = QtWidgets.QGroupBox("通用（AI 玩家共用）")
        temp_form = QtWidgets.QFormLayout(temp_box)
        self.temp = QtWidgets.QDoubleSpinBox()
        self.temp.setRange(0.0, 2.0)
        self.temp.setSingleStep(0.1)
        self.temp.setDecimals(2)
        self.temp.setValue(0.2)
        temp_form.addRow("Temperature", self.temp)
        self.chk_debug_log = QtWidgets.QCheckBox("开启 Debug 日志（写入 log/ 文件夹，重启生效）")
        self.chk_debug_log.setToolTip("开启后会在 log/ 文件夹中记录所有 API 请求/响应、游戏状态变化等详细信息")
        temp_form.addRow(self.chk_debug_log)

        self.btn_save_env = QtWidgets.QPushButton("💾 保存到 .env")
        self.btn_save_env.clicked.connect(self.on_save_env)

        layout.addWidget(a_box)
        layout.addWidget(b_box)
        layout.addWidget(c_box)
        layout.addWidget(temp_box)
        layout.addWidget(self.btn_save_env)
        layout.addStretch(1)

        scroll.setWidget(container)
        tab_layout = QtWidgets.QVBoxLayout(self.tab_settings)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    # ═══════════════════════════ 配置 加载/保存 ═══════════════════════════

    def _load_env_to_ui(self) -> None:
        env = core.load_dotenv(ENV_PATH)
        self.a_name.setText(env.get("A_NAME", "AI_A"))
        self.a_base.setText(env.get("A_BASE_URL", ""))
        self.a_key.setText(env.get("A_API_KEY", ""))
        self.a_model.setText(env.get("A_MODEL", ""))
        self.a_thinking.setChecked(env.get("A_THINKING_ENABLED", "").lower() == "true")
        try:
            self.a_thinking_budget.setValue(int(env.get("A_THINKING_BUDGET", "8000") or "8000"))
        except ValueError:
            pass
        self.a_memory.setChecked(env.get("A_MEMORY_ENABLED", "true").lower() != "false")
        self.a_temp.setText(env.get("A_TEMPERATURE", ""))

        self.b_name.setText(env.get("B_NAME", "AI_B"))
        self.b_base.setText(env.get("B_BASE_URL", ""))
        self.b_key.setText(env.get("B_API_KEY", ""))
        self.b_model.setText(env.get("B_MODEL", ""))
        self.b_thinking.setChecked(env.get("B_THINKING_ENABLED", "").lower() == "true")
        try:
            self.b_thinking_budget.setValue(int(env.get("B_THINKING_BUDGET", "8000") or "8000"))
        except ValueError:
            pass
        self.b_memory.setChecked(env.get("B_MEMORY_ENABLED", "true").lower() != "false")
        self.b_temp.setText(env.get("B_TEMPERATURE", ""))

        self.c_base.setText(env.get("COMMENTATOR_BASE_URL", ""))
        self.c_key.setText(env.get("COMMENTATOR_API_KEY", ""))
        self.c_model.setText(env.get("COMMENTATOR_MODEL", ""))
        try:
            self.c_temp.setValue(float(env.get("COMMENTATOR_TEMPERATURE", "0.7") or "0.7"))
        except ValueError:
            pass
        self.c_thinking.setChecked(env.get("COMMENTATOR_THINKING_ENABLED", "").lower() == "true")
        try:
            self.c_thinking_budget.setValue(int(env.get("COMMENTATOR_THINKING_BUDGET", "8000") or "8000"))
        except ValueError:
            pass
        self.c_on_action.setChecked(env.get("COMMENTATOR_ON_ACTION", "true").lower() != "false")
        self.c_on_street.setChecked(env.get("COMMENTATOR_ON_STREET", "true").lower() != "false")
        self.c_on_hand.setChecked(env.get("COMMENTATOR_ON_HAND", "true").lower() != "false")
        self.c_god_view.setChecked(env.get("COMMENTATOR_GOD_VIEW", "true").lower() != "false")

        try:
            self.temp.setValue(float(env.get("TEMPERATURE", "0.2") or "0.2"))
        except ValueError:
            self.temp.setValue(0.2)

        self.chk_debug_log.setChecked(env.get("DEBUG_LOG_ENABLED", "").strip().lower() == "true")

        try:
            self.stack_input.setValue(float(env.get("DEFAULT_STACK", "1000") or "1000"))
        except ValueError:
            pass
        try:
            self.sb_input.setValue(float(env.get("DEFAULT_SB", "2.5") or "2.5"))
        except ValueError:
            pass
        try:
            self.bb_input.setValue(float(env.get("DEFAULT_BB", "5") or "5"))
        except ValueError:
            pass

    def _collect_env_data(self) -> dict[str, str]:
        return {
            "A_NAME": self.a_name.text().strip() or "AI_A",
            "A_BASE_URL": self.a_base.text().strip(),
            "A_API_KEY": self.a_key.text().strip(),
            "A_MODEL": self.a_model.text().strip(),
            "A_THINKING_ENABLED": "true" if self.a_thinking.isChecked() else "false",
            "A_THINKING_BUDGET": str(self.a_thinking_budget.value()),
            "A_MEMORY_ENABLED": "true" if self.a_memory.isChecked() else "false",
            "A_TEMPERATURE": self.a_temp.text().strip(),
            "B_NAME": self.b_name.text().strip() or "AI_B",
            "B_BASE_URL": self.b_base.text().strip(),
            "B_API_KEY": self.b_key.text().strip(),
            "B_MODEL": self.b_model.text().strip(),
            "B_THINKING_ENABLED": "true" if self.b_thinking.isChecked() else "false",
            "B_THINKING_BUDGET": str(self.b_thinking_budget.value()),
            "B_MEMORY_ENABLED": "true" if self.b_memory.isChecked() else "false",
            "B_TEMPERATURE": self.b_temp.text().strip(),
            "DEFAULT_STACK": str(self.stack_input.value()),
            "DEFAULT_SB": str(self.sb_input.value()),
            "DEFAULT_BB": str(self.bb_input.value()),
            "TEMPERATURE": str(self.temp.value()),
            "COMMENTATOR_BASE_URL": self.c_base.text().strip(),
            "COMMENTATOR_API_KEY": self.c_key.text().strip(),
            "COMMENTATOR_MODEL": self.c_model.text().strip(),
            "COMMENTATOR_TEMPERATURE": str(self.c_temp.value()),
            "COMMENTATOR_THINKING_ENABLED": "true" if self.c_thinking.isChecked() else "false",
            "COMMENTATOR_THINKING_BUDGET": str(self.c_thinking_budget.value()),
            "COMMENTATOR_ON_ACTION": "true" if self.c_on_action.isChecked() else "false",
            "COMMENTATOR_ON_STREET": "true" if self.c_on_street.isChecked() else "false",
            "COMMENTATOR_ON_HAND": "true" if self.c_on_hand.isChecked() else "false",
            "COMMENTATOR_GOD_VIEW": "true" if self.c_god_view.isChecked() else "false",
            "DEBUG_LOG_ENABLED": "true" if self.chk_debug_log.isChecked() else "false",
        }

    def on_save_env(self) -> None:
        log.info("[UI] 点击: 保存配置到 .env")
        data = self._collect_env_data()
        core.save_dotenv(ENV_PATH, data)
        self.controller.load_env(data)
        log.info("[UI] 配置已保存 (%d 项)", len(data))
        QtWidgets.QMessageBox.information(self, "成功", "配置已保存至 .env")

    # ═══════════════════════════ 对局操作 ═══════════════════════════

    def on_new_match(self) -> None:
        log.info("[UI] 点击: 开始新比赛")
        try:
            start_stack = int(round(self.stack_input.value() * 100))
            sb = int(round(self.sb_input.value() * 100))
            bb = int(round(self.bb_input.value() * 100))
            self.log.clear()
            self.commentary.clear()
            self.controller.start_new_match(start_stack, sb, bb)
        except Exception as e:
            log.error("[UI] on_new_match 异常: %s", e)
            self.on_error(str(e))

    def on_next_hand(self) -> None:
        log.info("[UI] 点击: 开始下一手")
        try:
            self.controller.start_next_hand()
        except Exception as e:
            log.error("[UI] on_next_hand 异常: %s", e)
            self.on_error(str(e))

    def on_next_street(self) -> None:
        log.info("[UI] 点击: 发下一轮公共牌")
        try:
            self.controller.advance_street()
        except Exception as e:
            log.error("[UI] on_next_street 异常: %s", e)
            self.on_error(str(e))

    def on_showdown(self) -> None:
        log.info("[UI] 点击: 摊牌结算")
        try:
            self.controller.showdown()
        except Exception as e:
            log.error("[UI] on_showdown 异常: %s", e)
            self.on_error(str(e))

    def on_lock_cards(self) -> None:
        log.info("[UI] 点击: 确认指定牌面")
        try:
            def _cd(cb):
                v = cb.currentData()
                return v if v else None
            self.controller.lock_cards_from_texts(
                [_cd(self.a1), _cd(self.a2)],
                [_cd(self.b1), _cd(self.b2)],
                [_cd(self.f1), _cd(self.f2), _cd(self.f3), _cd(self.t1), _cd(self.r1)],
            )
        except Exception as e:
            log.error("[UI] on_lock_cards 异常: %s", e)
            self.on_error(str(e))

    def on_ensure_dealt(self) -> None:
        log.info("[UI] 点击: 随机补齐缺牌")
        try:
            self.controller.ensure_dealt_current_street()
        except Exception as e:
            log.error("[UI] on_ensure_dealt 异常: %s", e)
            self.on_error(str(e))

    def on_action(self, action: str) -> None:
        to_cents = None
        if action in ("bet", "raise"):
            to_cents = int(round(self.to_spin.value() * 100))
        log.info("[UI] 手动操作: action=%s to_cents=%s", action, to_cents)
        try:
            self.controller.execute_action(action, to_cents)  # type: ignore[arg-type]
        except Exception as e:
            log.error("[UI] on_action 异常: %s", e)
            self.on_error(str(e))

    def on_allin(self) -> None:
        if not self.vm:
            return
        legal = self.vm.legal
        if not legal.can_allin or not legal.allin_action:
            return
        log.info("[UI] 手动操作: ALL-IN | action=%s to_cents=%s", legal.allin_action, legal.allin_to_cents)
        try:
            self.controller.execute_action(legal.allin_action, legal.allin_to_cents)  # type: ignore[arg-type]
        except Exception as e:
            log.error("[UI] on_allin 异常: %s", e)
            self.on_error(str(e))

    def on_auto_start(self) -> None:
        log.info("[UI] 点击: 开始自动对局 | auto_fill=%s | auto_advance=%s | delay=%dms",
                 self.chk_auto_fill.isChecked(), self.chk_auto_advance.isChecked(), self.delay_ms.value())
        self.controller.set_auto_options(self.chk_auto_fill.isChecked(), self.chk_auto_advance.isChecked())
        self.controller.hand_interval_seconds = self.hand_interval_spin.value()
        self.controller.set_auto_running(True)
        self.timer.setInterval(self.delay_ms.value())
        self.timer.start()
        self.append_log("▶ 自动行动已开启")

    def on_auto_stop(self) -> None:
        log.info("[UI] 点击: 停止自动对局")
        self.timer.stop()
        self.controller.set_auto_running(False)
        self.append_log("■ 自动行动已停止")

    def on_delay_changed(self) -> None:
        if self.timer.isActive():
            self.timer.setInterval(self.delay_ms.value())

    def on_hand_interval_changed(self) -> None:
        self.controller.hand_interval_seconds = self.hand_interval_spin.value()

    def on_auto_options_changed(self) -> None:
        self.controller.set_auto_options(self.chk_auto_fill.isChecked(), self.chk_auto_advance.isChecked())

    def on_auto_tick(self) -> None:
        self.controller.auto_tick()

    # ═══════════════════════════ 日志 / 解说 ═══════════════════════════

    def append_log(self, line: str) -> None:
        self.log.append(line)

    def append_commentary(self, line: str) -> None:
        self.commentary.append(line)

    def on_error(self, msg: str) -> None:
        if not msg:
            return
        log.warning("[UI] 错误弹窗: %s", msg[:500])
        QtWidgets.QMessageBox.warning(self, "错误", msg)

    # ═══════════════════════════ ViewModel 刷新 ═══════════════════════════

    def _set_combo_by_code(self, combo: QtWidgets.QComboBox, code: str) -> None:
        combo.blockSignals(True)
        try:
            idx = combo.findData(code)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def on_vm_changed(self, vm: AppViewModel) -> None:
        self.vm = vm
        self.status.showMessage(vm.status_text + (f" | Auto: {vm.auto_state.paused_reason}" if vm.auto_state.paused_reason else ""))

        # 刷新可视化牌桌
        self.board_panel.update_state(vm)

        # 用自定义名称更新牌面标签
        na = vm.player_names.get("AI_A", "AI_A")
        nb = vm.player_names.get("AI_B", "AI_B")
        self.lbl_a_cards.setText(f"{na} 底牌")
        self.lbl_b_cards.setText(f"{nb} 底牌")

        self._set_combo_by_code(self.a1, vm.hole_cards["AI_A"][0])
        self._set_combo_by_code(self.a2, vm.hole_cards["AI_A"][1])
        self._set_combo_by_code(self.b1, vm.hole_cards["AI_B"][0])
        self._set_combo_by_code(self.b2, vm.hole_cards["AI_B"][1])
        self._set_combo_by_code(self.f1, vm.board_cards[0])
        self._set_combo_by_code(self.f2, vm.board_cards[1])
        self._set_combo_by_code(self.f3, vm.board_cards[2])
        self._set_combo_by_code(self.t1, vm.board_cards[3])
        self._set_combo_by_code(self.r1, vm.board_cards[4])

        self.history.clear()
        self.history.addItems(vm.history_lines)

        legal = vm.legal
        self.lbl_to_call.setText(f"需跟注: ${core.dollars_from_cents(legal.to_call_cents)}")

        self.btn_fold.setEnabled(legal.can_fold and not vm.thinking)
        self.btn_check.setEnabled(legal.can_check and not vm.thinking)
        self.btn_call.setEnabled(legal.can_call and not vm.thinking)
        self.btn_bet.setEnabled(legal.can_bet and not vm.thinking)
        self.btn_raise.setEnabled(legal.can_raise and not vm.thinking)
        self.btn_allin.setEnabled(legal.can_allin and not vm.thinking)

        if legal.can_allin and legal.allin_to_cents is not None:
            self.btn_allin.setText(f"全押 ${core.dollars_from_cents(legal.allin_to_cents)}")
        elif legal.can_allin:
            self.btn_allin.setText("全押 (All-In)")
        else:
            self.btn_allin.setText("全押 (All-In)")

        self.btn_next_street.setEnabled((not vm.hand_over) and (vm.next_to_act is None) and (vm.street != "river"))
        self.btn_showdown.setEnabled((not vm.hand_over) and (vm.next_to_act is None) and (vm.street == "river"))

        self.btn_auto_start.setEnabled(not vm.auto_state.running)
        self.btn_auto_stop.setEnabled(vm.auto_state.running)

        min_to = None
        if legal.can_bet and legal.min_bet_to_cents is not None:
            min_to = legal.min_bet_to_cents
        if legal.can_raise and legal.min_raise_to_cents is not None:
            min_to = legal.min_raise_to_cents if (min_to is None) else min(min_to, legal.min_raise_to_cents)

        if min_to is None:
            self.to_spin.setRange(0.0, max(0.0, legal.max_to_cents / 100))
        else:
            self.to_spin.setRange(min_to / 100, max(min_to / 100, legal.max_to_cents / 100))

        if legal.suggested_to_cents is not None:
            self.to_spin.setValue(legal.suggested_to_cents / 100)


def main() -> None:
    env = core.load_dotenv(ENV_PATH)
    debug_enabled = env.get("DEBUG_LOG_ENABLED", "").strip().lower() == "true"
    core.setup_logging(debug_enabled, base_dir=os.path.dirname(__file__))
    log.info("应用启动 | debug_log=%s | python=%s | platform=%s", debug_enabled, sys.version.split()[0], sys.platform)

    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()

    # 启动 WebSocket 服务器（供前端牌桌连接）
    ws_port = int(env.get("WS_PORT", "8002"))
    ws_manager = WebSocketManager(host="0.0.0.0", port=ws_port)
    w.controller.add_observer(ws_manager.broadcast_sync)
    ws_thread = threading.Thread(target=ws_manager.run, daemon=True)
    ws_thread.start()
    log.info("WebSocket 服务器已启动 | ws://0.0.0.0:%d/ws", ws_port)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
