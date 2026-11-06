import logging
import os
import sys
import sqlite3


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
import bots
import theme
from app_shell import AppShell
from table_widget import PokerTableWidget
from history_store import HistoryStore
from settings_widgets import ModelCombo, TemperatureInput, ProviderControls
from controller import AppViewModel, GameController, PlayerID

log = logging.getLogger("poker.ui")

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, history_store=None):
        super().__init__()
        self.setWindowTitle("短牌德州 LLM 对战引擎")
        self.resize(1600, 1000)

        history_error = None
        if history_store is None:
            try:
                history_store = HistoryStore()
            except (OSError, sqlite3.Error) as error:
                history_error = str(error)
        self.controller = GameController(history_store)
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
        self._update_config_hint(jump=True)
        if history_error:
            self.on_error("牌谱存储不可用（对局可继续）：" + history_error)

    # ═══════════════════════════ UI 构建 ═══════════════════════════

    def _build_ui(self) -> None:
        self._build_controls()
        self.shell = AppShell(self)
        self.controller.eventRaised.connect(self.on_event)

    def on_event(self, event):
        if event["type"] == "hand" and not all(bots.configured(p) or (p.base_url and p.api_key and p.model)
                                               for p in self.controller.profile.values()):
            return
        self.shell.timeline.add_event(event)

    def _build_controls(self) -> None:
        self.tab_game = QtWidgets.QWidget(self)
        self.tab_settings = QtWidgets.QWidget(self)
        self.tab_game.hide()
        self.tab_settings.hide()
        self._build_game_tab()
        self._build_settings_tab()
        self.error_bar = QtWidgets.QFrame()
        self.error_bar.setObjectName("notification")
        error_layout = QtWidgets.QVBoxLayout(self.error_bar)
        error_row = QtWidgets.QHBoxLayout()
        self.error_summary = QtWidgets.QLabel()
        self.error_summary.setWordWrap(True)
        self.error_details_button = QtWidgets.QPushButton("详情")
        self.error_details_button.setCheckable(True)
        dismiss = QtWidgets.QPushButton("关闭")
        error_row.addWidget(self.error_summary, 1)
        error_row.addWidget(self.error_details_button)
        error_row.addWidget(dismiss)
        error_layout.addLayout(error_row)
        self.error_details = QtWidgets.QPlainTextEdit()
        self.error_details.setReadOnly(True)
        self.error_details.setMaximumHeight(140)
        error_layout.addWidget(self.error_details)
        self.error_details.hide()
        self.error_details_button.toggled.connect(self.error_details.setVisible)
        dismiss.clicked.connect(self.error_bar.hide)
        self.error_timer = QtCore.QTimer(self)
        self.error_timer.setSingleShot(True)
        self.error_timer.timeout.connect(self.error_bar.hide)
        self.error_details_button.toggled.connect(lambda expanded: self.error_timer.stop() if expanded else self.error_timer.start(8000))
        self.error_bar.hide()

        self.board_panel = PokerTableWidget()

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(theme.font(9, mono=True))

        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)

    # ───────────────────── 对局 Tab ─────────────────────

    def _build_game_tab(self) -> None:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        scroll.setWidget(container)
        tab_layout = QtWidgets.QVBoxLayout(self.tab_game)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        self.config_banner = QtWidgets.QWidget()
        self.config_banner.setObjectName("configBanner")
        banner_layout = QtWidgets.QVBoxLayout(self.config_banner)
        banner_layout.addWidget(QtWidgets.QLabel("尚未配置 AI 选手，请先在设置页填写并测试连接"))
        jump = QtWidgets.QPushButton("前往设置")
        jump.clicked.connect(lambda: self.shell.show_settings())
        banner_layout.addWidget(jump)
        layout.addWidget(self.config_banner)

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
        self.btn_new_match.setProperty("variant", "primary")
        self.btn_new_match.setToolTip("重置双方筹码，开始一场全新比赛")
        self.btn_next_hand = QtWidgets.QPushButton("开始下一手")
        self.btn_next_hand.setProperty("variant", "secondary")
        self.btn_next_hand.setToolTip("当前手牌结束后，点此发下一手牌")
        row_start.addWidget(self.btn_new_match)
        row_start.addWidget(self.btn_next_hand)
        form.addRow(row_start)

        row_advance = QtWidgets.QHBoxLayout()
        self.btn_next_street = QtWidgets.QPushButton("发下一轮公共牌")
        self.btn_next_street.setProperty("variant", "secondary")
        self.btn_next_street.setToolTip("当前轮行动结束后，翻开下一轮公共牌（翻牌→转牌→河牌）")
        self.btn_showdown = QtWidgets.QPushButton("摊牌结算")
        self.btn_showdown.setProperty("variant", "secondary")
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
        for label in (self.lbl_a_cards, self.lbl_b_cards):
            label.setMaximumWidth(105)
            label.setWordWrap(True)

        cards_layout.addWidget(self.lbl_a_cards, 0, 0)
        cards_layout.addWidget(self.a1, 0, 1)
        cards_layout.addWidget(self.a2, 0, 2)

        cards_layout.addWidget(self.lbl_b_cards, 1, 0)
        cards_layout.addWidget(self.b1, 1, 1)
        cards_layout.addWidget(self.b2, 1, 2)

        cards_layout.addWidget(QtWidgets.QLabel("公共牌 · 翻牌 / 转牌 / 河牌"), 2, 0, 1, 3)
        cards_layout.addWidget(self.f1, 3, 0)
        cards_layout.addWidget(self.f2, 3, 1)
        cards_layout.addWidget(self.f3, 3, 2)
        cards_layout.addWidget(QtWidgets.QLabel("转牌 / 河牌"), 4, 0)
        cards_layout.addWidget(self.t1, 4, 1)
        cards_layout.addWidget(self.r1, 4, 2)

        self.btn_lock_cards = QtWidgets.QPushButton("确认指定")
        self.btn_lock_cards.setToolTip("将上面选择的牌锁定到本局")
        self.btn_ensure_dealt = QtWidgets.QPushButton("随机补齐缺牌")
        self.btn_ensure_dealt.setToolTip("未指定的位置自动随机发牌")
        self.btn_lock_cards.setProperty("variant", "ghost")
        self.btn_ensure_dealt.setProperty("variant", "secondary")
        card_buttons = QtWidgets.QHBoxLayout()
        card_buttons.addWidget(self.btn_lock_cards)
        card_buttons.addWidget(self.btn_ensure_dealt)
        cards_layout.addLayout(card_buttons, 5, 0, 1, 3)

        self.btn_lock_cards.clicked.connect(self.on_lock_cards)
        self.btn_ensure_dealt.clicked.connect(self.on_ensure_dealt)

        layout.addWidget(cards_box)

        # ── 手动操作（替 AI 做决策） ──
        actions_box = QtWidgets.QGroupBox("手动操作（替当前 AI 做决策）")
        actions_layout = QtWidgets.QGridLayout(actions_box)

        self.lbl_to_call = QtWidgets.QLabel("需跟注: $0.00")
        self.lbl_to_call.setProperty("role", "emphasis")
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

        self.btn_allin = QtWidgets.QPushButton("全押 (All-In)")
        self.btn_allin.setToolTip("押上全部筹码")

        self.btn_fold.setProperty("variant", "danger")
        self.btn_check.setProperty("variant", "secondary")
        self.btn_call.setProperty("variant", "secondary")
        self.btn_bet.setProperty("variant", "secondary")
        self.btn_raise.setProperty("variant", "secondary")
        self.btn_allin.setProperty("variant", "primary")

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
        self.btn_auto_start.setProperty("variant", "primary")
        self.btn_auto_stop.setProperty("variant", "danger")
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
        self.a_model = ModelCombo()
        self.a_thinking = QtWidgets.QCheckBox("开启深度思考 (thinking)")
        self.a_thinking_budget = QtWidgets.QSpinBox()
        self.a_thinking_budget.setRange(1000, 100000)
        self.a_thinking_budget.setSingleStep(1000)
        self.a_thinking_budget.setValue(8000)
        self.a_memory = QtWidgets.QCheckBox("启用本手牌记忆")
        self.a_memory.setChecked(True)
        self.a_temp = TemperatureInput()
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
        self.b_model = ModelCombo()
        self.b_thinking = QtWidgets.QCheckBox("开启深度思考 (thinking)")
        self.b_thinking_budget = QtWidgets.QSpinBox()
        self.b_thinking_budget.setRange(1000, 100000)
        self.b_thinking_budget.setSingleStep(1000)
        self.b_thinking_budget.setValue(8000)
        self.b_memory = QtWidgets.QCheckBox("启用本手牌记忆")
        self.b_memory.setChecked(True)
        self.b_temp = TemperatureInput()
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
        self.c_model = ModelCombo()
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
        self.ai_timeout = QtWidgets.QSpinBox()
        self.ai_timeout.setRange(0, 3600)
        self.ai_timeout.setSpecialValueText("自动（普通 60s / 思考 180s）")
        self.commentator_timeout = QtWidgets.QSpinBox()
        self.commentator_timeout.setRange(1, 3600)
        self.commentator_timeout.setValue(30)
        self.decision_retries = QtWidgets.QSpinBox()
        self.decision_retries.setRange(0, 10)
        self.decision_retries.setValue(2)
        self.clamp_sizing = QtWidgets.QCheckBox("越界自动夹值")
        self.clamp_sizing.setChecked(True)
        temp_form.addRow("选手请求超时（秒）", self.ai_timeout)
        temp_form.addRow("解说请求超时（秒）", self.commentator_timeout)
        temp_form.addRow("非法输出重答次数", self.decision_retries)
        temp_form.addRow(self.clamp_sizing)
        self.four_color_deck = QtWidgets.QCheckBox("四色牌面")
        self.show_equity = QtWidgets.QCheckBox("显示观众胜率（上帝视角）")
        self.reduce_motion = QtWidgets.QCheckBox("减少动画")
        self.four_color_deck.setChecked(True)
        self.show_equity.setChecked(True)
        temp_form.addRow(self.four_color_deck)
        temp_form.addRow(self.show_equity)
        temp_form.addRow(self.reduce_motion)
        self.chk_debug_log = QtWidgets.QCheckBox("开启 Debug 日志（写入 log/ 文件夹）")
        self.chk_debug_log.toggled.connect(lambda enabled: core.setup_logging(enabled, base_dir=os.path.dirname(__file__)))
        self.chk_debug_log.setToolTip("开启后会在 log/ 文件夹中记录所有 API 请求/响应、游戏状态变化等详细信息")
        temp_form.addRow(self.chk_debug_log)

        self.btn_save_env = QtWidgets.QPushButton("💾 保存到 .env")
        self.btn_save_env.clicked.connect(self.on_save_env)

        layout.addWidget(a_box)
        self.provider_controls = {
            "A": ProviderControls(self, "a", a_form, True),
            "B": ProviderControls(self, "b", b_form, True),
            "COMMENTATOR": ProviderControls(self, "c", c_form),
        }
        self.c_same = QtWidgets.QCheckBox("解说员与选手 A 相同")
        c_form.insertRow(0, self.c_same)
        self.c_same.toggled.connect(self._sync_commentator)
        for widget in (self.a_base, self.a_key):
            widget.textChanged.connect(self._sync_commentator)
        self.a_model.currentTextChanged.connect(self._sync_commentator)
        self.provider_controls["A"].provider.currentTextChanged.connect(self._sync_commentator)
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
        self.a_name.setText(env.get("A_NAME", "选手 A"))
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

        self.b_name.setText(env.get("B_NAME", "选手 B"))
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
        for widget, key, default in ((self.ai_timeout, "AI_TIMEOUT_S", 0),
                                     (self.commentator_timeout, "COMMENTATOR_TIMEOUT_S", 30),
                                     (self.decision_retries, "MAX_DECISION_RETRIES", 2)):
            try:
                widget.setValue(int(env.get(key, "") or default))
            except ValueError:
                widget.setValue(default)
        self.clamp_sizing.setChecked(env.get("CLAMP_OUT_OF_RANGE", "true").lower() != "false")
        self.four_color_deck.setChecked(env.get("FOUR_COLOR_DECK", "true").lower() != "false")
        self.show_equity.setChecked(env.get("SHOW_EQUITY", "true").lower() != "false")
        self.reduce_motion.setChecked(env.get("REDUCE_MOTION", "false").lower() == "true")
        for key, controls in self.provider_controls.items():
            controls.load(env, key)
        self.shell.dialog.format_controls.load(env)
        self.c_same.setChecked(env.get("COMMENTATOR_SAME_AS_A", "").lower() == "true")
        self._sync_commentator()

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
        data = {
            "A_NAME": self.a_name.text().strip() or "选手 A",
            "A_BASE_URL": self.a_base.text().strip(),
            "A_API_KEY": self.a_key.text().strip(),
            "A_MODEL": self.a_model.text().strip(),
            "A_THINKING_ENABLED": "true" if self.a_thinking.isChecked() else "false",
            "A_THINKING_BUDGET": str(self.a_thinking_budget.value()),
            "A_MEMORY_ENABLED": "true" if self.a_memory.isChecked() else "false",
            "A_TEMPERATURE": self.a_temp.text().strip(),
            "B_NAME": self.b_name.text().strip() or "选手 B",
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
        for key, controls in self.provider_controls.items():
            data.update(controls.collect(key))
        data.update(self.shell.dialog.format_controls.collect())
        data["COMMENTATOR_SAME_AS_A"] = "true" if self.c_same.isChecked() else "false"
        data["AI_TIMEOUT_S"] = str(self.ai_timeout.value()) if self.ai_timeout.value() else ""
        data["COMMENTATOR_TIMEOUT_S"] = str(self.commentator_timeout.value())
        data["MAX_DECISION_RETRIES"] = str(self.decision_retries.value())
        data["CLAMP_OUT_OF_RANGE"] = "true" if self.clamp_sizing.isChecked() else "false"
        data["FOUR_COLOR_DECK"] = "true" if self.four_color_deck.isChecked() else "false"
        data["SHOW_EQUITY"] = "true" if self.show_equity.isChecked() else "false"
        data["REDUCE_MOTION"] = "true" if self.reduce_motion.isChecked() else "false"
        return data

    def on_save_env(self) -> None:
        log.info("[UI] 点击: 保存配置到 .env")
        data = self._collect_env_data()
        core.save_dotenv(ENV_PATH, data)
        self.controller.load_env(data)
        log.info("[UI] 配置已保存 (%d 项)", len(data))
        self.statusBar().showMessage("配置已保存至 .env", 5000)
        self._update_config_hint()

    def _sync_commentator(self, *_args) -> None:
        same = self.c_same.isChecked()
        for name in ("base", "key", "model"):
            widget = getattr(self, "c_" + name)
            if same:
                widget.setText(getattr(self, "a_" + name).text())
            widget.setEnabled(not same)
        controls = self.provider_controls["COMMENTATOR"]
        if same:
            controls.provider.blockSignals(True)
            controls.provider.setCurrentText(self.provider_controls["A"].provider.currentText())
            controls.provider.blockSignals(False)
        controls.provider.setEnabled(not same)
        controls.fetch.setEnabled(not same)

    def closeEvent(self, event) -> None:
        if any(controls.jobs for controls in self.provider_controls.values()):
            self.statusBar().showMessage("连接请求进行中，请稍后关闭窗口", 3000)
            event.ignore()
            return
        self.shell.save_state()
        self.controller.set_auto_running(False)
        super().closeEvent(event)

    def _update_config_hint(self, jump=False) -> bool:
        configured = all(bots.configured(p) or (p.base_url.strip() and p.api_key.strip() and p.model.strip())
                         for p in self.controller.profile.values())
        if hasattr(self, "shell"):
            self.shell.set_configured(configured)
        return bool(configured)

    # ═══════════════════════════ 对局操作 ═══════════════════════════

    def on_new_match(self) -> None:
        if getattr(self, "_match_started", False) and not self.controller.match_finished and self.vm and all(v > 0 for v in self.vm.stacks_cents.values()):
            if QtWidgets.QMessageBox.question(self, "开始新比赛", "当前比赛尚未结束，确定重置筹码并开始新比赛？",
                                             QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                             QtWidgets.QMessageBox.StandardButton.No) != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        log.info("[UI] 点击: 开始新比赛")
        try:
            start_stack = int(round(self.stack_input.value() * 100))
            sb = int(round(self.sb_input.value() * 100))
            bb = int(round(self.bb_input.value() * 100))
            self.log.clear()
            self.controller.start_new_match(start_stack, sb, bb)
            self._match_started = True
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
        if not self._update_config_hint():
            self.statusBar().showMessage("尚未配置 AI 选手，请先在设置页填写并测试连接", 8000)
            return
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
        self.log.append(self.controller.display_text(line))

    def append_commentary(self, line: str) -> None:
        self.append_log(line)

    def on_error(self, msg: str) -> None:
        if not msg:
            return
        self.error_bar.setProperty("tone", "error")
        self.error_bar.style().unpolish(self.error_bar)
        self.error_bar.style().polish(self.error_bar)
        log.warning("[UI] 错误通知: %s", msg[:500])
        self.error_summary.setText("⚠️ " + msg.splitlines()[0][:160])
        self.error_details.setPlainText(msg)
        self.error_details_button.setChecked(False)
        self.error_details.hide()
        self.error_bar.show()
        self.error_timer.start(8000)

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
        self.status.showMessage(vm.status_text + (f" · 自动对局：{vm.auto_state.paused_reason}" if vm.auto_state.paused_reason else ""))

        # 刷新可视化牌桌
        self.board_panel.update_state(vm)

        na = vm.player_names.get("AI_A", "AI_A")
        nb = vm.player_names.get("AI_B", "AI_B")
        self.lbl_a_cards.setText("选手 A 底牌")
        self.lbl_b_cards.setText("选手 B 底牌")
        self.lbl_a_cards.setToolTip(na)
        self.lbl_b_cards.setToolTip(nb)

        self._set_combo_by_code(self.a1, vm.hole_cards["AI_A"][0])
        self._set_combo_by_code(self.a2, vm.hole_cards["AI_A"][1])
        self._set_combo_by_code(self.b1, vm.hole_cards["AI_B"][0])
        self._set_combo_by_code(self.b2, vm.hole_cards["AI_B"][1])
        self._set_combo_by_code(self.f1, vm.board_cards[0])
        self._set_combo_by_code(self.f2, vm.board_cards[1])
        self._set_combo_by_code(self.f3, vm.board_cards[2])
        self._set_combo_by_code(self.t1, vm.board_cards[3])
        self._set_combo_by_code(self.r1, vm.board_cards[4])

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
        if hasattr(self, "shell"):
            self.shell.update_state(vm)


def main() -> None:
    env = core.load_dotenv(ENV_PATH)
    debug_enabled = env.get("DEBUG_LOG_ENABLED", "").strip().lower() == "true"
    core.setup_logging(debug_enabled, base_dir=os.path.dirname(__file__))
    log.info("应用启动 | debug_log=%s | python=%s | platform=%s", debug_enabled, sys.version.split()[0], sys.platform)

    app = QtWidgets.QApplication(sys.argv)
    theme.apply(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
