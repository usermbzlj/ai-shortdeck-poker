import json
import logging
import random
import sqlite3
import threading
import time as _time
import uuid
import weakref
from dataclasses import dataclass, field, replace
from typing import Literal

from PySide6 import QtCore

import core
import bots
import equity
from history_capture import HandTrace
from match import MatchRules, MatchLedger, combine_stats
import prompts
import providers
import humans

log = logging.getLogger("poker.ctrl")

PlayerID = Literal["AI_A", "AI_B"]


def _schedule(delay_ms: int, callback) -> None:
    QtCore.QTimer.singleShot(delay_ms, callback)


def _safe_format(template: str, ctx: dict) -> str:
    """用 ctx 替换 template 中的 {占位符}，忽略未知占位符和格式错误。"""
    try:
        return template.format_map(ctx)
    except (KeyError, ValueError):
        result = template
        for k, v in ctx.items():
            result = result.replace("{" + k + "}", str(v))
        return result


@dataclass(frozen=True)
class ActionAvailability:
    can_fold: bool
    can_check: bool
    can_call: bool
    can_bet: bool
    can_raise: bool
    can_allin: bool
    allin_action: str | None      # "bet" / "raise" / "call" — 全押时实际执行的动作
    allin_to_cents: int | None    # 全押时的 to_cents 值
    disabled_reason: str | None
    to_call_cents: int
    min_bet_to_cents: int | None
    min_raise_to_cents: int | None
    max_to_cents: int
    suggested_to_cents: int | None


@dataclass(frozen=True)
class AutoState:
    running: bool
    paused_reason: str | None
    auto_fill_missing: bool
    auto_advance_street: bool


@dataclass(frozen=True)
class AppViewModel:
    hand_id: int
    button: PlayerID
    street: core.Street
    pot_cents: int
    stacks_cents: dict[PlayerID, int]
    hole_cards: dict[PlayerID, list[str]]
    board_cards: list[str]
    next_to_act: PlayerID | None
    legal: ActionAvailability
    status_text: str
    history_lines: list[str]
    hand_over: bool
    winner: PlayerID | None
    reason: str | None
    thinking: bool
    last_error: str | None
    auto_state: AutoState
    player_names: dict[PlayerID, str]
    contributed_street_cents: dict[PlayerID, int]
    model_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    model_names: dict[str, str] = field(default_factory=dict)
    thinking_started: float = 0.0
    last_trash_talk: dict[str, str] = field(default_factory=dict)
    trash_talk_times: dict[str, float] = field(default_factory=dict)
    last_analysis: dict[str, str] = field(default_factory=dict)
    winner_hand_desc: str = ""
    best_five: list[str] = field(default_factory=list)
    pot_won_cents: int = 0
    four_color_deck: bool = True
    show_equity: bool = True
    reduce_motion: bool = False
    hands_won: dict[str, int] = field(default_factory=dict)
    total_hands: int = 0
    blind_level: int = 1
    blinds_text: str = ""
    seats_swapped: bool = False
    match_finished: bool = False
    human_player: str | None = None
    human_turn: bool = False
    privacy_active: bool = False
    god_view: bool = False


@dataclass
class LLMProfile:
    thinking_param: bool = True
    persona: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float | None = 0.2
    name: str = ""
    thinking_enabled: bool = False
    thinking_budget: int = 8000
    memory_enabled: bool = True


@dataclass
class CommentatorProfile:
    thinking_param: bool = True
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float | None = 0.7
    thinking_enabled: bool = False
    thinking_budget: int = 8000
    on_action: bool = True
    on_street: bool = True
    on_hand: bool = True
    god_view: bool = True

    @property
    def configured(self) -> bool:
        return self.base_url not in (bots.BASE_URL, humans.BASE_URL) and bool(self.base_url and self.api_key and self.model)


class GameController(QtCore.QObject):
    handCompleted = QtCore.Signal(object)
    matchStarted = QtCore.Signal()
    _allinResult = QtCore.Signal(str, int, object)
    matchFinished = QtCore.Signal(object)
    summaryChanged = QtCore.Signal(object)
    blindLevelChanged = QtCore.Signal(str)
    eventRaised = QtCore.Signal(object)
    viewModelChanged = QtCore.Signal(object)
    logAppended = QtCore.Signal(str)
    commentaryAppended = QtCore.Signal(str)
    errorRaised = QtCore.Signal(str)

    _llmResult = QtCore.Signal(int, str, str, str, object)
    _llmError = QtCore.Signal(int, str, str)          # req_id, player, error_msg
    _commentResult = QtCore.Signal(str, int, int, str, bool)
    _commentError = QtCore.Signal(str)
    _reactionResult = QtCore.Signal(int, str, str, str)

    def __init__(self, history_store=None):
        super().__init__()
        self._llmResult.connect(self._handle_llm_result)
        self._llmError.connect(self._handle_llm_error)
        self._commentResult.connect(lambda mid, hand, frame, text, private: self._handle_comment_result(text, mid, hand, frame, private))
        self._commentError.connect(self._handle_comment_error)
        self._reactionResult.connect(lambda generation, player, label, text:
                                     self._handle_reaction_result(player, label, text, generation))
        self._match_generation = 0
        self.history_store = history_store
        self._trace = None
        self.god_view_override = False
        self._private_events = []
        self._human_started = 0.
        self._records = {}
        self._allinResult.connect(self._on_allin_equity)
        self.state = core.HandState("AI_A", "AI_B")

        self.profile: dict[PlayerID, LLMProfile] = {"AI_A": LLMProfile(), "AI_B": LLMProfile()}
        self.commentator = CommentatorProfile()

        self._hand_memory: dict[PlayerID, list[dict]] = {"AI_A": [], "AI_B": []}

        self.thinking = False
        self.auto_running = False
        self.skip_action_commentary = False
        self.rules = MatchRules()
        self.active_rules = self.rules
        self.ledger = MatchLedger()
        self.match_summary = None
        self.match_finished = False
        self._duplicate_pending = False
        self._first_leg = None
        self._base_blinds = (250, 500)
        self._replay_limit = 0
        self.bot_delay_ms = 1000
        self._bot_rng = random.Random()
        self.auto_fill_missing = True
        self.auto_advance_street = True

        self.request_id = 0
        self.active_request_id = 0
        self.last_error: str | None = None
        self._paused_reason: str | None = None

        self._consecutive_failures = 0
        self.max_consecutive_failures = 3
        self.max_decision_retries = 2
        self.clamp_sizing = True
        self.ai_timeout_s = None
        self.commentator_timeout_s = 30
        self._decision_messages = []
        self._decision_retries = 0
        self._network_retries = 0
        self.thinking_started = 0.0
        self._trash_talk_times = {}
        self.four_color_deck = True
        self.show_equity = True
        self.reduce_motion = False
        self.model_stats = {p: dict.fromkeys(("decisions", "invalid_outputs", "retries", "fallbacks", "clamps"), 0)
                            for p in ("AI_A", "AI_B")}

        # 喊话记忆（当前手牌）
        self._last_trash_talk: dict[PlayerID, str] = {"AI_A": "", "AI_B": ""}
        # 最近分析摘要
        self._last_analysis: dict[PlayerID, str] = {"AI_A": "", "AI_B": ""}
        # 比赛统计
        self._match_stats = {"total_hands": 0, "wins": {"AI_A": 0, "AI_B": 0}}
        # 上一条解说（防重复）
        self._prev_commentary: str = ""
        # 手牌间隔延迟
        self._hand_end_ts: float = 0.0
        self.hand_interval_seconds: float = 3.0
        # 等待选手心理活动 / 赛后感言完成
        self._pending_reactions: int = 0

        self._emit_vm()

    def _display_name(self, pid: PlayerID) -> str:
        name = self.profile[pid].name
        return name if name and name not in ("AI_A", "AI_B") else ("选手 A" if pid == "AI_A" else "选手 B")

    def display_text(self, text: str) -> str:
        for pid in ("AI_A", "AI_B"):
            text = text.replace(pid, self._display_name(pid))
        return text

    def emit_event(self, kind, text, player=None, amount=None, private=False):
        if self.human_player and player != self.human_player and kind == "reasoning" and not self.state.hand_over:
            self._private_events.append((kind, text, player, amount))
            if not self.god_view_override:
                return
            private = True
        self.eventRaised.emit(dict(type=kind, player=player,
                                   name=self._display_name(player) if player else "",
                                   text=self.display_text(text), amount=amount,
                                   hand_id=self.state.hand_id, match_id=getattr(self, "match_id", None), private=private))

    @property
    def human_player(self):
        return next((p for p, profile in self.profile.items() if humans.configured(profile)), None)

    @property
    def privacy_active(self):
        return bool(self.human_player and not self.god_view_override and not self.state.hand_over)

    def set_god_view(self, enabled):
        self.god_view_override = bool(enabled)
        self._emit_vm()

    def execute_human_action(self, action, to_cents=None, trash_talk=""):
        player = self.human_player
        if not player or self.state.next_to_act != player or self.state.hand_over or self.thinking:
            raise core.UserFacingError("当前还没有轮到你行动。")
        humans.validate_action(self.state, player, action, to_cents)
        speech = trash_talk.strip()[:200]
        if speech:
            self._last_trash_talk[player] = speech
            self._trash_talk_times[player] = _time.monotonic()
            self.emit_event("speech", speech, player)
        elapsed = max(0., _time.monotonic() - self._human_started) if self._human_started else 0.
        self.model_stats[player]["decisions"] += 1
        self.ledger.times[player].append(elapsed)
        self._human_started = 0.
        self.execute_action(action, to_cents, dict(analysis="", trash_talk=speech, think_seconds=elapsed, tokens={}))
        if self.auto_running and not self.state.hand_over:
            self.auto_tick()

    def _action_event(self, player, action, amount):
        if self._trace is not None:
            self._trace.after_action(self.state, player, action, amount, self._last_analysis, self._last_trash_talk)
            self._detect_allin()
        self.ledger.action(self.state, player, action)
        text = {"fold": "弃牌", "check": "过牌", "call": "跟注", "bet": "下注", "raise": "加注"}[action]
        self.emit_event("action", text, player, amount)

    def pause(self):
        self.auto_running = False
        self._paused_reason = "已暂停"
        self._emit_vm()

    def single_step(self):
        self.pause()
        if self.thinking:
            return
        self.auto_running = True
        try:
            self.auto_tick()
        finally:
            self.pause()

    @staticmethod
    def _parse_temp(raw: str, fallback: str = "") -> float | None:
        """解析温度值。空串 / 'none' 返回 None（不发送），否则返回 float。"""
        v = (raw or "").strip().lower()
        if not v or v == "none":
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def load_env(self, env: dict[str, str]) -> None:
        humans.validate_env(env)
        env = dict(env)
        for seat in ("A", "B"):
            if env.get(seat + "_PROVIDER") == humans.PROVIDER or env.get(seat + "_BASE_URL") == humans.BASE_URL:
                env.update({seat + "_BASE_URL": humans.BASE_URL, seat + "_MODEL": "真人", seat + "_API_KEY": ""})
        previous_human = self.human_player
        self.rules = MatchRules.from_env(env)
        self.four_color_deck = env.get("FOUR_COLOR_DECK", "true").lower() != "false"
        self.show_equity = env.get("SHOW_EQUITY", "true").lower() != "false"
        self.reduce_motion = env.get("REDUCE_MOTION", "false").lower() == "true"
        self.max_decision_retries = max(0, int(env.get("MAX_DECISION_RETRIES", "2") or "2"))
        self.clamp_sizing = env.get("CLAMP_OUT_OF_RANGE", "true").lower() != "false"
        self.ai_timeout_s = int(env["AI_TIMEOUT_S"]) if env.get("AI_TIMEOUT_S", "").strip() else None
        self.commentator_timeout_s = int(env.get("COMMENTATOR_TIMEOUT_S", "30") or "30")
        if env.get("COMMENTATOR_SAME_AS_A", "").lower() == "true":
            env = dict(env)
            for suffix in ("BASE_URL", "API_KEY", "MODEL", "PROVIDER"):
                env["COMMENTATOR_" + suffix] = env.get("A_" + suffix, "")
            env["COMMENTATOR_PROVIDER"] = env.get("A_PROVIDER") or providers.infer_provider(env.get("A_BASE_URL", ""))
        log.info("load_env: 加载配置 (%d 项)", len(env))
        global_temp = env.get("TEMPERATURE", "").strip()

        def resolve_temp(per_ai_key: str, default: str = "") -> float | None:
            raw = env.get(per_ai_key, "").strip()
            if raw:
                return self._parse_temp(raw)
            if global_temp:
                return self._parse_temp(global_temp)
            return self._parse_temp(default)

        self.profile["AI_A"] = LLMProfile(
            thinking_param=providers.sends_thinking(env.get("A_THINKING_PARAM", "auto"), env.get("A_PROVIDER", providers.infer_provider(env.get("A_BASE_URL", "")))),
            persona=env.get("A_PERSONA", prompts.A_EXTRA_INSTRUCTIONS),
            base_url=env.get("A_BASE_URL", ""),
            api_key=env.get("A_API_KEY", ""),
            model=env.get("A_MODEL", ""),
            temperature=resolve_temp("A_TEMPERATURE", "0.2"),
            name=env.get("A_NAME", "").strip() or "AI_A",
            thinking_enabled=env.get("A_THINKING_ENABLED", "").lower() == "true",
            thinking_budget=int(env.get("A_THINKING_BUDGET", "8000") or "8000"),
            memory_enabled=env.get("A_MEMORY_ENABLED", "true").lower() != "false",
        )
        self.profile["AI_B"] = LLMProfile(
            thinking_param=providers.sends_thinking(env.get("B_THINKING_PARAM", "auto"), env.get("B_PROVIDER", providers.infer_provider(env.get("B_BASE_URL", "")))),
            persona=env.get("B_PERSONA", prompts.B_EXTRA_INSTRUCTIONS),
            base_url=env.get("B_BASE_URL", ""),
            api_key=env.get("B_API_KEY", ""),
            model=env.get("B_MODEL", ""),
            temperature=resolve_temp("B_TEMPERATURE", "0.2"),
            name=env.get("B_NAME", "").strip() or "AI_B",
            thinking_enabled=env.get("B_THINKING_ENABLED", "").lower() == "true",
            thinking_budget=int(env.get("B_THINKING_BUDGET", "8000") or "8000"),
            memory_enabled=env.get("B_MEMORY_ENABLED", "true").lower() != "false",
        )
        self.commentator = CommentatorProfile(
            thinking_param=providers.sends_thinking(env.get("COMMENTATOR_THINKING_PARAM", "auto"), env.get("COMMENTATOR_PROVIDER", providers.infer_provider(env.get("COMMENTATOR_BASE_URL", "")))),
            base_url=env.get("COMMENTATOR_BASE_URL", ""),
            api_key=env.get("COMMENTATOR_API_KEY", ""),
            model=env.get("COMMENTATOR_MODEL", ""),
            temperature=self._parse_temp(env.get("COMMENTATOR_TEMPERATURE", ""), "0.7"),
            thinking_enabled=env.get("COMMENTATOR_THINKING_ENABLED", "").lower() == "true",
            thinking_budget=int(env.get("COMMENTATOR_THINKING_BUDGET", "8000") or "8000"),
            on_action=env.get("COMMENTATOR_ON_ACTION", "true").lower() != "false",
            on_street=env.get("COMMENTATOR_ON_STREET", "true").lower() != "false",
            on_hand=env.get("COMMENTATOR_ON_HAND", "true").lower() != "false",
            god_view=env.get("COMMENTATOR_GOD_VIEW", "true").lower() != "false",
        )
        log.info(
            "配置加载完成 | AI_A: name=%s model=%s thinking=%s memory=%s | AI_B: name=%s model=%s thinking=%s memory=%s | 解说员: model=%s configured=%s",
            self.profile["AI_A"].name, self.profile["AI_A"].model,
            self.profile["AI_A"].thinking_enabled, self.profile["AI_A"].memory_enabled,
            self.profile["AI_B"].name, self.profile["AI_B"].model,
            self.profile["AI_B"].thinking_enabled, self.profile["AI_B"].memory_enabled,
            self.commentator.model, self.commentator.configured,
        )
        if previous_human != self.human_player:
            self._invalidate_requests()
            self.auto_running = False
            self.god_view_override = False
            self._human_started = 0.
        if self.human_player and self.state.hand_id:
            self.state.ensure_dealt(self.state.street)
        if self._trace and not self._trace.record["actions"] and not self.state.hand_over:
            self._start_trace()
            if not self._records:
                self._metadata.update(names=dict(self._trace.names), models=dict(self._trace.models))
        self._emit_vm()

    def set_auto_options(self, fill_missing: bool, auto_advance_street: bool) -> None:
        self.auto_fill_missing = bool(fill_missing)
        self.auto_advance_street = bool(auto_advance_street)
        self._emit_vm()

    def _clear_hand_memory(self) -> None:
        self._hand_memory = {"AI_A": [], "AI_B": []}

    def start_new_match(self, start_stack_cents: int, sb_cents: int, bb_cents: int,
                        *, seed=None, deck_sequence=None, swap_seats=False) -> None:
        if sum(humans.configured(p) for p in self.profile.values()) > 1:
            raise core.UserFacingError("目前只支持一个真人座位。")
        self._private_events = []
        self._human_started = 0.
        log.info("start_new_match | stack=%d | sb=%d | bb=%d", start_stack_cents, sb_cents, bb_cents)
        self._invalidate_requests()
        self._match_generation += 1
        self.auto_running = False
        self._paused_reason = None
        self._consecutive_failures = 0
        self.thinking_started = 0.0
        self.active_rules = self.rules
        self.ledger = MatchLedger()
        self.match_summary = None
        self.match_finished = False
        self._duplicate_pending = False
        self._base_blinds = (sb_cents, bb_cents)
        self.model_stats = {p: dict.fromkeys(("decisions", "invalid_outputs", "retries", "fallbacks", "clamps"), 0)
                            for p in ("AI_A", "AI_B")}
        if not swap_seats:
            self._first_leg = None
            self._replay_limit = 0
        self.last_error = None
        self._clear_hand_memory()
        self._last_trash_talk = {"AI_A": "", "AI_B": ""}
        self._trash_talk_times = {}
        self._last_analysis = {"AI_A": "", "AI_B": ""}
        self._match_stats = {"total_hands": 0, "wins": {"AI_A": 0, "AI_B": 0}}
        self._prev_commentary = ""
        self._hand_end_ts = 0.0
        self._pending_reactions = 0
        self.state.sb_cents = sb_cents
        self.state.bb_cents = bb_cents
        self.state.new_match(start_stack_cents, seed=seed, deck_sequence=deck_sequence, swap_seats=swap_seats)
        if self.human_player:
            self.state.ensure_dealt("preflop")
        self.match_id = uuid.uuid4().hex
        self._records = {}
        self._metadata = dict(id=self.match_id, created_at=core.now_iso(),
                              names={p: self._display_name(p) for p in self.state.players},
                              models={p: self.profile[p].model for p in self.state.players},
                              initial_stack_cents=start_stack_cents, sb_cents=sb_cents, bb_cents=bb_cents,
                              swapped=swap_seats, format=self.active_rules.format)
        self._start_trace()
        self.matchStarted.emit()
        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")
        self.logAppended.emit("--- \U0001f195 新比赛开始 ---")
        self.logAppended.emit(f"初始筹码：${core.dollars_from_cents(start_stack_cents)} · 盲注：${core.dollars_from_cents(sb_cents)}/${core.dollars_from_cents(bb_cents)}")
        self.logAppended.emit(f"第 {self.state.hand_id} 手 · 庄家：{self._display_name(self.state.button)}")
        self.emit_event("hand", f"—— 第 {self.state.hand_id} 手 ——")
        self._emit_vm()

    def start_next_hand(self) -> None:
        if self.match_finished:
            raise core.UserFacingError("比赛已结束，请开始新比赛或交换座位复赛")
        self._private_events = []
        self._human_started = 0.
        log.info("start_next_hand")
        self._invalidate_requests()
        self.last_error = None
        self._clear_hand_memory()
        self._last_trash_talk = {"AI_A": "", "AI_B": ""}
        self._trash_talk_times = {}
        self._last_analysis = {"AI_A": "", "AI_B": ""}
        next_hand = self.state.hand_id + 1
        old_level = self.active_rules.level(self.state.hand_id)
        self.state.sb_cents, self.state.bb_cents = self.active_rules.blinds(*self._base_blinds, next_hand)
        self.state.start_hand()
        if self.human_player:
            self.state.ensure_dealt("preflop")
        self._start_trace()
        if self.active_rules.level(next_hand) != old_level:
            text = f"盲注升至第 {self.active_rules.level(next_hand) + 1} 级 · 小盲 $" + core.dollars_from_cents(self.state.sb_cents) + " / 大盲 $" + core.dollars_from_cents(self.state.bb_cents)
            self.emit_event("system", text)
            self.blindLevelChanged.emit(text)
        self.emit_event("hand", f"—— 第 {self.state.hand_id} 手 ——")
        self.logAppended.emit(f"第 {self.state.hand_id} 手 · 庄家：{self._display_name(self.state.button)}")
        self._emit_vm()

    def lock_cards_from_texts(
        self,
        a_cards: list[str | None],
        b_cards: list[str | None],
        board_cards: list[str | None],
    ) -> None:
        self._invalidate_requests()
        hole_a = [core.parse_card(t) if t else None for t in a_cards[:2]]
        hole_b = [core.parse_card(t) if t else None for t in b_cards[:2]]

        board_prefix: list[core.Card | None] = []
        seen_empty = False
        for t in board_cards[:5]:
            if t:
                if seen_empty:
                    raise core.UserFacingError("公共牌请从左到右锁定，不能跳格锁定。")
                board_prefix.append(core.parse_card(t))
            else:
                seen_empty = True

        self.state.lock_cards(hole_a, hole_b, board_prefix)
        self._emit_vm()

    def ensure_dealt_current_street(self) -> None:
        self._invalidate_requests()
        self.state.ensure_dealt(self.state.street)
        self._emit_vm()

    def execute_action(self, action: core.Action, to_cents: int | None, decision=None) -> None:
        player = self.state.next_to_act
        if player and humans.configured(self.profile[player]) and decision is None:
            return self.execute_human_action(action, to_cents)
        log.info("execute_action (手动) | action=%s | to_cents=%s | next_to_act=%s", action, to_cents, self.state.next_to_act)
        self._invalidate_requests()
        self.last_error = None
        p = self.state.next_to_act
        if not p:
            raise core.UserFacingError("当前无需行动")
        amount = self.state.to_call_cents(p) if action == "call" else to_cents
        self._trace.before_action(self.state, p, decision=decision, analysis=self._last_analysis, speech=self._last_trash_talk)
        self.state.apply_action(p, action, to_cents)
        self._action_event(p, action, amount)
        if self.state.hand_over and self.state.win_reason == "fold":
            self._update_match_stats(self.state.winner)
            self._hand_end_ts = _time.monotonic()
            self.emit_event("system", f"{self._display_name(self.state.winner)} 赢得底池 · 对手弃牌")
            self._trigger_commentary("本手结束 · 对手弃牌", is_hand_end=True)
            self._trigger_player_reactions()
        log.debug("execute_action 完成 | hand_over=%s | next_to_act=%s | pot=%d", self.state.hand_over, self.state.next_to_act, self.state.pot_cents)
        self._emit_vm()

    def advance_street(self) -> None:
        log.info("advance_street 请求 | 当前=%s", self.state.street)
        self._invalidate_requests()
        self.last_error = None
        self.state.advance_street()
        self._trace.frame(self.state, "进入" + {"flop": "翻牌", "turn": "转牌", "river": "河牌"}[self.state.street],
                          self._last_analysis, self._last_trash_talk)
        self._detect_allin()
        street_name = {"preflop": "翻牌前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}[self.state.street]
        self.emit_event("system", f"进入{street_name}")
        self.logAppended.emit(f"=== 进阶到 {street_name} ===")
        self._trigger_commentary(f"进入 {street_name}")
        self._emit_vm()

    def showdown(self) -> None:
        log.info("showdown 请求")
        self._invalidate_requests()
        self.last_error = None
        self.state.resolve_showdown()
        if self.state.winner:
            winner_name = self._display_name(self.state.winner)
            res = f"摊牌结束 · 主池赢家：{winner_name}"
        else:
            res = "主池平局"
        self.logAppended.emit(f"{res} (原因: {self.state.win_reason})")
        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")
        self.logAppended.emit(
            f"\U0001f3e6 结算后 | {na}: ${core.dollars_from_cents(self.state.stacks['AI_A'])} | {nb}: ${core.dollars_from_cents(self.state.stacks['AI_B'])}"
        )
        self._update_match_stats(self.state.winner)
        self.emit_event("system", res)
        self._hand_end_ts = _time.monotonic()
        self._trigger_commentary("本手结束 — 摊牌", is_hand_end=True)
        self._trigger_player_reactions()
        self._emit_vm()

    def set_auto_running(self, running: bool) -> None:
        if running and self.match_finished and not self._duplicate_pending:
            return
        log.info("set_auto_running: %s → %s", self.auto_running, running)
        self.auto_running = bool(running)
        if self.auto_running:
            self._paused_reason = None
            self._consecutive_failures = 0
        else:
            self._invalidate_requests()
        self._emit_vm()

    def auto_tick(self) -> None:
        if not self.auto_running:
            return
        if self.thinking:
            return

        s = self.state.get_public_state()
        log.debug("auto_tick | hand_over=%s | next_to_act=%s | street=%s | auto_advance=%s", s.hand_over, s.next_to_act, s.street, self.auto_advance_street)

        if s.hand_over:
            if self.match_finished:
                if self._duplicate_pending and _time.monotonic() - self._hand_end_ts >= self.hand_interval_seconds:
                    self.start_duplicate()
                    self.set_auto_running(True)
                return
            # 等待心理活动 / 赛后感言输出完毕
            if self._pending_reactions > 0:
                return
            if any(v <= 0 for v in s.stacks_cents.values()):
                self.auto_running = False
                self._paused_reason = "比赛结束（一方筹码归零）"
                self._trigger_player_reactions(is_match_end=True)
                self._emit_vm()
                return
            # 等待手牌间隔
            if self._hand_end_ts > 0 and _time.monotonic() - self._hand_end_ts < self.hand_interval_seconds:
                return
            try:
                self.start_next_hand()
                self.logAppended.emit("▶ 自动开始下一手")
            except Exception as e:
                self._pause_auto("自动开始下一手失败", str(e))
            return

        if s.next_to_act is None:
            if self.auto_advance_street:
                if s.street == "river":
                    try:
                        self.showdown()
                    except Exception as e:
                        self._pause_auto("摊牌失败", str(e))
                    return
                try:
                    self.advance_street()
                except Exception as e:
                    self._pause_auto("推进街失败", str(e))
                return

            self.auto_running = False
            if s.street == "river":
                self._paused_reason = "本街结束，请点「摊牌」"
            else:
                self._paused_reason = "本街结束，请点「下一街」"
            self._emit_vm()
            return

        if self.auto_fill_missing:
            try:
                self.state.ensure_dealt(self.state.street)
            except Exception as e:
                self._pause_auto("补牌失败", str(e))
                return

        self.request_ai_decision()

    # ─────────────────────────── AI 决策请求 ───────────────────────────

    def request_ai_decision(self, messages: list[dict] | None = None) -> None:
        p = self.state.next_to_act
        if not p:
            return
        if self.thinking:
            return
        if humans.configured(self.profile[p]):
            self._emit_vm()
            return
        if messages is None:
            self._decision_retries = 0
            self._network_retries = 0
            self.model_stats[p]["decisions"] += 1
            messages = self._build_llm_messages(p)
        self._decision_messages = messages

        self.request_id += 1
        req_id = self.request_id
        self.active_request_id = req_id
        self.thinking = True
        self.thinking_started = _time.monotonic()
        self.last_error = None
        self._emit_vm()

        prof = self.profile[p]
        if bots.configured(prof):
            reply = bots.decide(self.state, p, prof.model, self._bot_rng)
            QtCore.QTimer.singleShot(self.bot_delay_ms, self,
                lambda: self._handle_llm_result(req_id, p, json.dumps(reply, ensure_ascii=False), ""))
            return
        client = core.LLMClient(prof.base_url, prof.api_key, prof.model,
                                timeout_s=self.ai_timeout_s or (180 if prof.thinking_enabled else 60))
        temperature = prof.temperature
        thinking_enabled = prof.thinking_enabled
        thinking_budget = prof.thinking_budget

        pname = self._display_name(p)
        log.info(
            "request_ai_decision | player=%s(%s) | req_id=%d | model=%s | thinking=%s | memory_msgs=%d",
            p, pname, req_id, prof.model, thinking_enabled, len(self._hand_memory[p]),
        )
        log.debug("AI 请求 messages (%d条):\n%s", len(messages), json.dumps(messages, ensure_ascii=False, indent=2)[:10000])
        self.logAppended.emit(f"[{pname}] 正在思考... (request_id={req_id})")

        def worker():
            start = _time.monotonic()
            try:
                result = client.chat(
                    messages=messages,
                    temperature=temperature,
                    thinking_enabled=thinking_enabled,
                    thinking_budget=thinking_budget,
                    thinking_param=prof.thinking_param,
                )
            except Exception as e:
                log.error("AI 请求异常 | req_id=%d | player=%s | %.2fs | %s", req_id, p, _time.monotonic() - start, e)
                self._llmError.emit(req_id, p, str(e))
                return
            elapsed = _time.monotonic() - start
            content = result.get("content", "")
            reasoning = result.get("reasoning_content") or ""
            log.info("AI 响应 | req_id=%d | player=%s | %.2fs | content_len=%d | reasoning_len=%d", req_id, p, elapsed, len(content), len(reasoning))
            log.debug("AI 响应 content:\n%s", content[:5000])
            if reasoning:
                log.debug("AI 响应 reasoning:\n%s", reasoning[:5000])
            self._llmResult.emit(req_id, p, content, reasoning, result.get("usage"))

        threading.Thread(target=worker, daemon=True).start()

    def _build_llm_messages(self, player: PlayerID) -> list[dict]:
        s = self.state.get_public_state()
        legal = self.state.legal_actions(player)

        pot = s.pot_cents
        opp: PlayerID = "AI_B" if player == "AI_A" else "AI_A"

        hole = [core.card_to_text(c) for c in s.hole[player] if c is not None]
        board = [core.card_to_text(c) for c in s.board if c is not None]

        pname = self._display_name(player)
        oname = self._display_name(opp)

        # ── System（仅身份占位符，无动态局面） ──
        raw_system = prompts.A_SYSTEM if player == "AI_A" else prompts.B_SYSTEM
        system = _safe_format(raw_system, {"player": pname, "opponent": oname})
        if self.profile[player].persona.strip():
            system += "\n\n═══ 你的风格 ═══\n" + self.profile[player].persona.strip()

        # ── User 消息：按「信息 → 历史 → 约束 → 要求」分组 ──
        actions = legal.get("actions", [])
        has_sizing = "bet" in actions or "raise" in actions
        to_call = int(legal.get("to_call_cents", 0))
        my_stack = s.stacks_cents[player]
        opp_stack = s.stacks_cents[opp]
        eff_stack = min(my_stack, opp_stack)

        is_sb = (s.button == player)
        position = "SB (Button, 庄家位)" if is_sb else "BB (大盲位)"
        preflop_order = "你先行动" if is_sb else "对手先行动"
        postflop_order = "对手先行动" if is_sb else "你先行动"

        my_street_contrib = self.state.contributed_street.get(player, 0)
        opp_street_contrib = self.state.contributed_street.get(opp, 0)

        parts: list[str] = []

        # Section 1: 身份与位置
        parts.append(
            f"═══ 身份 ═══\n"
            f"你是 {pname} | 对手是 {oname}\n"
            f"位置：{position} | Preflop {preflop_order}，Postflop {postflop_order}\n"
            f"盲注：SB {core.dollars_from_cents(s.sb_cents)} / BB {core.dollars_from_cents(s.bb_cents)} USD"
        )

        # Section 2: 可见信息
        hole_str = " ".join(hole) if hole else "（未发牌）"
        board_str = " ".join(board) if board else "（无）"
        parts.append(
            f"═══ 当前局面 ═══\n"
            f"Hand #{s.hand_id} | 街：{s.street}\n"
            f"你的底牌：{hole_str}\n"
            f"公共牌：{board_str}\n"
            f"底池：{pot} 分 (${core.dollars_from_cents(pot)})\n"
            f"你的筹码：{my_stack} 分 (${core.dollars_from_cents(my_stack)}) | "
            f"对手筹码：{opp_stack} 分 (${core.dollars_from_cents(opp_stack)})\n"
            f"有效筹码：{eff_stack} 分 (${core.dollars_from_cents(eff_stack)})\n"
            f"本街已投入：你 {my_street_contrib} 分 | 对手 {opp_street_contrib} 分"
        )

        # Section 3: 行动历史
        if s.action_history:
            parts.append(
                f"═══ 行动历史 ═══\n" +
                "\n".join(s.action_history)
            )
        else:
            parts.append("═══ 行动历史 ═══\n（本手尚无行动记录）")

        # Section 4: 约束（合法动作 + 下注边界）
        constraint_lines = [
            f"═══ 你的行动要求 ═══",
            f"合法动作：{', '.join(actions)}",
            f"需跟注额：{to_call} 分 (${core.dollars_from_cents(to_call)})",
        ]
        if has_sizing:
            raw_min_raise_to = legal.get("min_raise_to_cents")
            raw_max_to = legal.get("max_to_cents")
            eff_min_raise_to = raw_min_raise_to
            if raw_min_raise_to is not None and raw_max_to is not None and raw_min_raise_to > raw_max_to:
                eff_min_raise_to = raw_max_to
            min_bet_to = legal.get("min_bet_to_cents")
            if min_bet_to is not None:
                constraint_lines.append(f"bet 最小目标额：{min_bet_to} 分")
            if eff_min_raise_to is not None:
                constraint_lines.append(f"raise 最小目标额：{eff_min_raise_to} 分")
            if raw_max_to is not None:
                constraint_lines.append(f"最大目标额 (all-in)：{raw_max_to} 分")
            constraint_lines.append(
                "提醒：to_cents 是你本街投入目标总额（raise TO），不是增量（raise BY）。"
            )
        parts.append("\n".join(constraint_lines))

        # Section 5: 社交上下文（对手喊话）
        opp_talk = self._last_trash_talk.get(opp, "")
        if opp_talk:
            parts.append(f"═══ 对手喊话 ═══\n{oname} 对你说：「{opp_talk}」")

        # Section 6: 输出要求
        format_lines = [
            "═══ 输出要求 ═══",
            "输出且仅输出一个 JSON：",
            '  {"analysis": "≤60字中文决策理由", '
            f'"action": "{"|".join(actions)}"'
        ]
        if has_sizing:
            min_val = legal.get("min_bet_to_cents") or legal.get("min_raise_to_cents") or 0
            max_val = legal.get("max_to_cents", 0)
            if max_val > 0 and min_val > max_val:
                min_val = max_val
            format_lines[-1] += f', "to_cents": {min_val}~{max_val}'
        format_lines[-1] += ', "trash_talk": "可选喊话"}'
        parts.append("\n".join(format_lines))

        user_content = "\n\n".join(parts)

        messages: list[dict] = [{"role": "system", "content": system}]

        prof = self.profile[player]
        if prof.memory_enabled and self._hand_memory[player]:
            messages.extend(self._hand_memory[player])

        messages.append({"role": "user", "content": user_content})
        return messages

    def _handle_llm_error(self, req_id: int, player: str, err: str) -> None:
        log.warning("_handle_llm_error | req_id=%d | active=%d | player=%s | err=%s", req_id, self.active_request_id, player, err[:500])
        if req_id != self.active_request_id:
            log.debug("忽略过期请求 req_id=%d (active=%d)", req_id, self.active_request_id)
            return
        if self.auto_running and self._decision_messages and self._network_retries < 3:
            delay = 2 ** self._network_retries
            self._network_retries += 1
            self.logAppended.emit(f"⚠️ [{self._display_name(player)}] 请求失败，{delay}s 后重试 ({self._network_retries}/3)")
            self.last_error = err
            self.thinking = True
            _schedule(delay * 1000, lambda: self._resume_request(req_id, player, True))
            self._emit_vm()
            return
        self._handle_ai_failure(player, err)

    def _resume_request(self, req_id: int, player: str, auto_only=False) -> None:
        if req_id != self.active_request_id or self.state.next_to_act != player:
            return
        self.thinking = False
        if auto_only and not self.auto_running:
            self._emit_vm()
            return
        self.request_ai_decision(list(self._decision_messages))

    def _validated_decision(self, player: str, content: str):
        decision = core.Decision.from_text(content, allow_nonpositive=True)
        original_action = decision.action
        clamps_before = self.model_stats[player]["clamps"]
        legal = self.state.legal_actions(player)
        actions = legal.get("actions", [])
        action = decision.action
        if action == "call" and legal.get("to_call_cents", 0) == 0:
            action = "check"
        if action == "bet" and "bet" not in actions and "raise" in actions:
            action = "raise"
        elif action == "raise" and "raise" not in actions and "bet" in actions:
            action = "bet"
        if action not in actions:
            raise core.UserFacingError(f"你给的 action={action} 不合法")
        decision = replace(decision, action=action)
        if action in ("bet", "raise"):
            maximum = legal["max_to_cents"]
            minimum = min(legal.get("min_bet_to_cents" if action == "bet" else "min_raise_to_cents") or 1, maximum)
            amount = decision.to_cents
            if amount < minimum or amount > maximum:
                if self.clamp_sizing or self._decision_retries >= self.max_decision_retries:
                    amount = max(minimum, min(maximum, amount))
                    self.model_stats[player]["invalid_outputs"] += 1
                    self.model_stats[player]["clamps"] += 1
                    self.logAppended.emit(f"⚠️ [{self._display_name(player)}] 越界自动夹值：{decision.to_cents} → {amount}")
                    decision = replace(decision, to_cents=amount)
                else:
                    relation = f"小于最小值 {minimum}" if amount < minimum else f"超出最大值 {maximum}"
                    raise core.UserFacingError(f"你给的 to_cents={amount} {relation}")
        if action != original_action:
            if self.model_stats[player]["clamps"] == clamps_before:
                self.model_stats[player]["invalid_outputs"] += 1
            self.logAppended.emit(f"⚠️ [{self._display_name(player)}] 动作修正：{original_action} → {action}")
        return decision

    def _recover_decision(self, req_id, player, content, error):
        self.emit_event("warning", "输出不合法：" + error, player)
        self.model_stats[player]["invalid_outputs"] += 1
        legal = self.state.legal_actions(player)
        if self._decision_retries < self.max_decision_retries:
            self._decision_retries += 1
            self.model_stats[player]["retries"] += 1
            self._network_retries = 0
            messages = list(self._decision_messages or self._build_llm_messages(player))
            messages.extend([{"role": "assistant", "content": content},
                             {"role": "user", "content": f"{error}。合法动作及范围（单位：分）：{json.dumps(legal, ensure_ascii=False)}。请重新输出 JSON。"}])
            self._decision_messages = messages
            self.thinking = True
            self.logAppended.emit(f"⚠️ [{self._display_name(player)}] 输出不合法，要求重答 ({self._decision_retries}/{self.max_decision_retries})")
            self._emit_vm()
            _schedule(0, lambda: self._resume_request(req_id, player))
            return None
        self.model_stats[player]["fallbacks"] += 1
        action = "check" if "check" in legal.get("actions", []) else "fold"
        self.logAppended.emit(f"🛟 兜底动作 [{self._display_name(player)}] {action.upper()}：{error}")
        return core.Decision(action, None, "", "", {"action": action})

    def _handle_llm_result(self, req_id: int, player: str, content: str, reasoning: str, usage=None) -> None:
        log.debug("_handle_llm_result | req_id=%d | active=%d | player=%s", req_id, self.active_request_id, player)
        if req_id != self.active_request_id:
            log.debug("忽略过期请求 req_id=%d (active=%d)", req_id, self.active_request_id)
            return
        self.thinking = False
        pid: PlayerID = player  # type: ignore[assignment]
        pname = self._display_name(pid)
        try:
            # 显示思考过程
            if reasoning:
                self.emit_event("reasoning", reasoning, pid)
                short = reasoning[:500] + ("..." if len(reasoning) > 500 else "")
                self.logAppended.emit(f"🧠 [{pname}] 内心思考: {short}")

            try:
                decision = self._validated_decision(player, content)
            except (core.UserFacingError, ValueError, TypeError, KeyError) as error:
                decision = self._recover_decision(req_id, player, content, str(error))
                if decision is None:
                    return
            if decision.analysis:
                self.emit_event("reasoning", decision.analysis, pid)
                self.logAppended.emit(f"\U0001f4a1 [{pname}] 推理: {decision.analysis}")
                self._last_analysis[pid] = decision.analysis[:200]

            if decision.trash_talk:
                self.emit_event("speech", decision.trash_talk, pid)
                self._last_trash_talk[pid] = decision.trash_talk
                self._trash_talk_times[pid] = _time.monotonic()
                self.logAppended.emit(f"🗣️ [{pname} 喊话]: \"{decision.trash_talk}\"")

            # 存入记忆（user 消息 + assistant 回复）
            prof = self.profile[pid]
            if prof.memory_enabled:
                msgs = self._build_llm_messages(pid)
                last_user = msgs[-1]
                self._hand_memory[pid].append(last_user)
                applied_reply = json.dumps(dict(decision.raw, action=decision.action,
                                                to_cents=decision.to_cents), ensure_ascii=False)
                self._hand_memory[pid].append({"role": "assistant", "content": applied_reply})

            # 在 apply_action 之前保存底池快照（fold 会立即清零 pot）
            pot_before = self.state.pot_cents

            amount = self.state.to_call_cents(pid) if decision.action == "call" else decision.to_cents
            elapsed = max(0, _time.monotonic() - self.thinking_started) if self.thinking_started else 0
            self._trace.before_action(self.state, pid, dict(analysis=decision.analysis, trash_talk=decision.trash_talk,
                think_seconds=elapsed, tokens={k: v for k, v in (usage if isinstance(usage, dict) else {}).items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, (int, float))}),
                self._last_analysis, self._last_trash_talk)
            if self.thinking_started:
                self.ledger.times[pid].append(max(0, _time.monotonic() - self.thinking_started))
            self.state.apply_action(player, decision.action, decision.to_cents)
            self._action_event(pid, decision.action, amount)
            action_cn = {"fold": "弃牌", "check": "过牌", "call": "跟注", "bet": "下注", "raise": "加注"}[decision.action]
            action_line = f"{pname} 决定：{action_cn}"
            if decision.to_cents is not None:
                action_line += f" 至 ${core.dollars_from_cents(decision.to_cents)}"
            self.logAppended.emit(action_line)

            if self.state.hand_over and self.state.win_reason == "fold":
                winner_name = self._display_name(self.state.winner) if self.state.winner else "?"
                self.emit_event("system", f"{winner_name} 赢得底池 · 对手弃牌")
                self.logAppended.emit(f"\U0001f451 {winner_name} 赢得底池 (对手弃牌)")
                na = self._display_name("AI_A")
                nb = self._display_name("AI_B")
                self.logAppended.emit(
                    f"\U0001f3e6 结算后 | {na}: ${core.dollars_from_cents(self.state.stacks['AI_A'])} | {nb}: ${core.dollars_from_cents(self.state.stacks['AI_B'])}"
                )
                self._update_match_stats(self.state.winner)
                self._hand_end_ts = _time.monotonic()
                self._trigger_commentary(
                    f"{pname} 弃牌 — 本手结束（底池 ${core.dollars_from_cents(pot_before)}）",
                    is_hand_end=True,
                    pot_override_cents=pot_before,
                )
                self._trigger_player_reactions()
            else:
                event_text = f"{pname} {decision.action.upper()}"
                if decision.to_cents is not None:
                    event_text += f" to ${core.dollars_from_cents(decision.to_cents)}"
                self._trigger_commentary(event_text, is_action=True)

        except Exception as e:
            self._handle_ai_failure(player, str(e))
            return
        self._consecutive_failures = 0
        self._decision_messages = []
        self.active_request_id = 0
        self._emit_vm()

    # ─────────────────────────── 比赛统计 ──────────────────────────

    def _update_match_stats(self, winner: str | None) -> None:
        if not self.ledger.finish_hand(self.state):
            return
        if self.human_player:
            self.emit_event("system", "本手揭晓 · AI 推理与本手决策")
            events, self._private_events = self._private_events, []
            for kind, text, player, amount in events:
                self.emit_event(kind, "本手揭晓 · " + text, player, amount)
        record = self._trace.finish(self.state, self.model_stats, self._last_analysis, self._last_trash_talk)
        self._records[self.state.hand_id] = record
        self._save_record(record)
        self.handCompleted.emit(record)
        self._match_stats["total_hands"] += 1
        if winner in ("AI_A", "AI_B"):
            self._match_stats["wins"][winner] += 1
        if self.active_rules.ended(self.state) or (self._replay_limit and self.state.hand_id >= self._replay_limit):
            self._finish_match()

    def _finish_match(self):
        self.match_finished = True
        self._hand_end_ts = _time.monotonic()
        self._duplicate_pending = self.active_rules.duplicate and not self.state.replay_swapped
        if not self._duplicate_pending:
            self.auto_running = False
        self._paused_reason = "比赛结束"
        s = self.state
        net = {p: s.stacks[p] - s.start_stack_cents for p in s.players}
        combined = {p: net[p] + (self._first_leg["net_cents"][p] if self._first_leg else 0) for p in s.players}
        stats = self.ledger.stats(self.model_stats)
        if self._first_leg:
            stats = combine_stats(self._first_leg["stats"], stats, self._first_leg["hands"], self.ledger.hands)
        winner = max(combined, key=combined.get) if len(set(combined.values())) > 1 else None
        self.match_summary = dict(winner=winner, names={p: self._display_name(p) for p in s.players},
                                  stacks_cents=dict(s.stacks), net_cents=net,
                                  combined_cents=combined, hands=self.ledger.hands,
                                  biggest_pot_cents=self.ledger.biggest_pot,
                                  stats=stats, reflections={},
                                  seed=s.match_seed, deck_sequence=[[core.card_to_text(c) for c in d] for d in s.deck_sequence],
                                  initial_stack_cents=s.start_stack_cents,
                                  initial_blinds_cents=dict(sb=self._base_blinds[0], bb=self._base_blinds[1]),
                                  rules=dict(format=self.active_rules.format, hands=self.active_rules.hands,
                                             level_hands=self.active_rules.level_hands, duplicate=self.active_rules.duplicate),
                                  chip_curve=[dict(hand_no=0, stacks={p: s.start_stack_cents for p in s.players}, record=None)] +
                                  [dict(hand_no=h["hand_no"], stacks=h["final_stacks"], record=None) for h in self._records.values()],
                                  duplicate=bool(self._first_leg), first_leg=self._first_leg)
        self._trigger_player_reactions(is_match_end=True)
        if self.history_store:
            try:
                self.history_store.finish_match(self.match_id, self.match_summary)
            except (OSError, sqlite3.Error) as error:
                self.errorRaised.emit("总结保存失败：" + str(error))
        if not self._duplicate_pending:
            self.matchFinished.emit(self.match_summary)
        self.emit_event("system", "首场结束，准备交换座位复赛" if self._duplicate_pending else "比赛结束 · 赛后总结已生成")

    def start_duplicate(self):
        if not self.match_finished or self.match_summary is None:
            raise core.UserFacingError("请先完成一场比赛")
        if self.state.replay_swapped:
            raise core.UserFacingError("已完成交换座位复赛，请开始新比赛")
        first = self.match_summary
        seed, decks = self.state.match_seed, [list(d) for d in self.state.deck_sequence]
        stack, (sb, bb) = self.state.start_stack_cents, self._base_blinds
        self._first_leg = first
        self._replay_limit = self.ledger.hands
        rules = self.active_rules
        self.start_new_match(stack, sb, bb, seed=seed, deck_sequence=decks, swap_seats=True)
        self.active_rules = rules
        self.emit_event("system", "交换座位复赛 · 使用首场相同牌序")
        self._emit_vm()

    def start_demo(self):
        for pid, style in (("AI_A", "紧凶"), ("AI_B", "松凶")):
            self.profile[pid] = LLMProfile(base_url=bots.BASE_URL, model=style,
                                           name="蓝 · 紧凶" if pid == "AI_A" else "红 · 松凶")
        self.commentator = CommentatorProfile()
        self.rules = MatchRules("fixed", 12, 4)
        self.start_new_match(20000, 100, 200)
        self.set_auto_running(True)
        self.emit_event("system", "离线演示已开始 · 无需 API Key · 不会覆盖已保存配置")

    # ─────────────────────── 选手心理活动 / 赛后感想 ───────────────────────

    def _build_reaction_common_ctx(self) -> dict:
        """构建心理活动 / 感想共用的上下文信息。"""
        s = self.state.get_public_state()
        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")
        a_hole = " ".join(core.card_to_text(c) for c in s.hole["AI_A"] if c is not None) or "未知"
        b_hole = " ".join(core.card_to_text(c) for c in s.hole["AI_B"] if c is not None) or "未知"
        board = " ".join(core.card_to_text(c) for c in s.board if c is not None) or "无"
        action_history = " → ".join(s.action_history) or "无"

        talk_parts = []
        for pid_key in ("AI_A", "AI_B"):
            t = self._last_trash_talk.get(pid_key, "")
            if t:
                talk_parts.append(f"{self._display_name(pid_key)}: \"{t}\"")
        trash_talk_section = "本手喊话：" + " | ".join(talk_parts) + "\n" if talk_parts else ""

        hand_eval_section = ""
        a_cards = [cc for cc in s.hole["AI_A"] if cc is not None]
        b_cards = [cc for cc in s.hole["AI_B"] if cc is not None]
        board_raw = [cc for cc in s.board if cc is not None]
        if len(board_raw) >= 3 and len(a_cards) == 2 and len(b_cards) == 2:
            a_desc = core.best_hand_desc(a_cards, board_raw)
            b_desc = core.best_hand_desc(b_cards, board_raw)
            if a_desc and b_desc:
                hand_eval_section = f"最终牌型：{na} = {a_desc}，{nb} = {b_desc}"

        return {
            "na": na, "nb": nb,
            "a_hole": a_hole, "b_hole": b_hole,
            "board": board, "action_history": action_history,
            "trash_talk_section": trash_talk_section,
            "hand_eval_section": hand_eval_section,
            "s": s,
        }

    def _trigger_player_reactions(self, *, is_match_end: bool = False) -> None:
        if self.match_finished and not is_match_end:
            return
        """手牌结束后向双方 AI 各发一次请求，获取心理活动或赛后感想。"""
        common = self._build_reaction_common_ctx()
        s = common["s"]
        na, nb = common["na"], common["nb"]

        if is_match_end:
            final_stacks = f"{na}: ${core.dollars_from_cents(s.stacks_cents['AI_A'])} | {nb}: ${core.dollars_from_cents(s.stacks_cents['AI_B'])}"
            winner = max(s.stacks_cents, key=s.stacks_cents.get)
            total = self._match_stats["total_hands"]
            last_hand = f"底牌 {common['a_hole']} vs {common['b_hole']} | 公共牌 {common['board']} | 行动 {common['action_history']}"
            if common["hand_eval_section"]:
                last_hand += f" | {common['hand_eval_section']}"
            for pid in ("AI_A", "AI_B"):
                pname = self._display_name(pid)
                opp: PlayerID = "AI_B" if pid == "AI_A" else "AI_A"
                opp_name = self._display_name(opp)
                ctx = {
                    "player": pname, "opponent": opp_name,
                    "total_hands": str(total),
                    "my_wins": str(self._match_stats["wins"].get(pid, 0)),
                    "opp_wins": str(self._match_stats["wins"].get(opp, 0)),
                    "final_stacks": final_stacks,
                    "last_hand_summary": last_hand,
                    "trash_talk_section": common["trash_talk_section"],
                }
                label = f"🏆 [{pname} 赛后感言]"
                self._fire_reaction_request(pid, prompts.PLAYER_MATCH_END, ctx, label)
        else:
            if s.winner:
                result_text = f"{self._display_name(s.winner)} 赢得底池（{s.win_reason}）"
            else:
                result_text = "平局，平分底池"
            for pid in ("AI_A", "AI_B"):
                pname = self._display_name(pid)
                opp_id: PlayerID = "AI_B" if pid == "AI_A" else "AI_A"
                opp_name = self._display_name(opp_id)
                my_hole = common["a_hole"] if pid == "AI_A" else common["b_hole"]
                opp_hole = common["b_hole"] if pid == "AI_A" else common["a_hole"]
                ctx = {
                    "player": pname, "opponent": opp_name,
                    "my_hole": my_hole, "opp_hole": opp_hole,
                    "board_cards": common["board"],
                    "action_history": common["action_history"],
                    "trash_talk_section": common["trash_talk_section"],
                    "hand_eval_section": common["hand_eval_section"],
                    "result": result_text,
                }
                label = f"💭 [{pname} 内心]"
                self._fire_reaction_request(pid, prompts.PLAYER_REACTION, ctx, label)

    def _fire_reaction_request(self, pid: PlayerID, template: str, ctx: dict, label: str) -> None:
        prof = self.profile[pid]
        if humans.configured(prof):
            if self.match_summary:
                self.match_summary["reflections"][pid] = "真人选手 · 精彩判断，留待复盘。"
            return
        if bots.configured(prof):
            self._pending_reactions += 1
            winner = self.match_summary.get("winner") if self.match_summary else self.state.winner
            result = "赢" if winner == pid else "平" if winner is None else "输"
            self._handle_reaction_result(pid, label, bots.reflection(prof.model, result))
            return
        if not prof.base_url or not prof.api_key or not prof.model:
            return
        self._pending_reactions += 1
        generation = self._match_generation
        text = _safe_format(template, ctx)
        client = core.LLMClient(prof.base_url, prof.api_key, prof.model,
                                timeout_s=self.ai_timeout_s or (180 if prof.thinking_enabled else 60))
        messages = [{"role": "user", "content": text}]
        temp = prof.temperature
        t_enabled = prof.thinking_enabled
        t_budget = prof.thinking_budget

        def worker():
            try:
                result = client.chat(messages=messages, temperature=temp,
                                     thinking_enabled=t_enabled, thinking_budget=t_budget,
                                     thinking_param=prof.thinking_param)
                content = (result.get("content") or "").strip()
                if content:
                    self._reactionResult.emit(generation, pid, label, content)
                else:
                    self._reactionResult.emit(generation, pid, label, "")
            except Exception as e:
                log.warning("选手反应请求失败 | %s | %s", label, e)
                self._reactionResult.emit(generation, pid, label, "")

        threading.Thread(target=worker, daemon=True).start()

    def _handle_reaction_result(self, player: str, label: str, text: str, generation=None) -> None:
        if generation is not None and generation != self._match_generation:
            return
        self._pending_reactions = max(0, self._pending_reactions - 1)
        if self.match_summary is not None and "赛后感言" in label:
            self.match_summary["reflections"][player] = text or "感言暂不可用，仍可查看统计、导出或开始下一场。"
            self.summaryChanged.emit(self.match_summary)
            if self.history_store:
                try:
                    self.history_store.finish_match(self.match_id, self.match_summary)
                except (OSError, sqlite3.Error) as error:
                    self.errorRaised.emit("感言保存失败：" + str(error))
        if text:
            self.emit_event("monologue", text, player)
            self.commentaryAppended.emit(f"{label}: \"{text}\"")

    # ─────────────────────────── 解说员 ───────────────────────────

    def _trigger_commentary(
        self, event: str, *,
        is_action: bool = False, is_hand_end: bool = False,
        pot_override_cents: int | None = None,
    ) -> None:
        c = self.commentator
        if not c.configured:
            return

        is_street_event = not is_action and not is_hand_end
        if is_action and (not c.on_action or self.skip_action_commentary):
            return
        if is_street_event and not c.on_street:
            return
        if is_hand_end and not c.on_hand:
            return

        s = self.state.get_public_state()
        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")
        board = [core.card_to_chinese(core.card_to_text(cc)) for cc in s.board if cc is not None]

        god_section = ""
        hand_eval_section = ""
        public_only = bool(self.human_player and s.win_reason != "showdown")
        if public_only:
            count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[s.street]
            board = board[:count]
        if c.god_view and not public_only:
            a_hole = [core.card_to_chinese(core.card_to_text(cc)) for cc in s.hole["AI_A"] if cc is not None]
            b_hole = [core.card_to_chinese(core.card_to_text(cc)) for cc in s.hole["AI_B"] if cc is not None]
            god_section = f"- {na} 底牌：{' '.join(a_hole) or '未发'} | {nb} 底牌：{' '.join(b_hole) or '未发'}"

            a_cards = [cc for cc in s.hole["AI_A"] if cc is not None]
            b_cards = [cc for cc in s.hole["AI_B"] if cc is not None]
            board_raw = [cc for cc in s.board if cc is not None]
            if len(board_raw) >= 3 and len(a_cards) == 2 and len(b_cards) == 2:
                a_desc = core.best_hand_desc(a_cards, board_raw)
                b_desc = core.best_hand_desc(b_cards, board_raw)
                if a_desc and b_desc:
                    hand_eval_section = f"- 【系统计算】当前最佳成牌：{na} = {a_desc}，{nb} = {b_desc}"
                    if is_hand_end and s.win_reason == "showdown":
                        if s.winner:
                            hand_eval_section += f"。{self._display_name(s.winner)} 获胜"
                        else:
                            hand_eval_section += "。平局，平分底池"

        pot_cents = pot_override_cents if pot_override_cents is not None else s.pot_cents

        stats = self._match_stats
        match_stats = f"第 {stats['total_hands'] + (0 if is_hand_end else 1)} 手 | {na} 赢了 {stats['wins']['AI_A']} 手，{nb} 赢了 {stats['wins']['AI_B']} 手"

        analyses_parts = []
        for pid_key in ("AI_A", "AI_B"):
            a_text = "" if public_only else self._last_analysis.get(pid_key, "")
            if a_text:
                analyses_parts.append(f"{self._display_name(pid_key)}: {a_text}")
        player_analyses = " | ".join(analyses_parts) if analyses_parts else "暂无"

        talk_parts = []
        for pid_key in ("AI_A", "AI_B"):
            t = self._last_trash_talk.get(pid_key, "")
            if t:
                talk_parts.append(f"{self._display_name(pid_key)}: \"{t}\"")
        trash_talk_section = "- 本轮喊话：" + " | ".join(talk_parts) if talk_parts else ""

        ctx = {
            "event": event,
            "street": s.street,
            "pot_usd": core.dollars_from_cents(pot_cents),
            "player_a": na,
            "player_b": nb,
            "a_stack_usd": core.dollars_from_cents(s.stacks_cents["AI_A"]),
            "b_stack_usd": core.dollars_from_cents(s.stacks_cents["AI_B"]),
            "board_cards": " ".join(board) or "无",
            "god_view_section": god_section,
            "hand_eval_section": hand_eval_section,
            "action_history": " | ".join(s.action_history[-6:]) or "无",
            "match_stats": match_stats,
            "player_analyses": player_analyses,
            "trash_talk_section": trash_talk_section,
            "prev_commentary": "无" if public_only else self._prev_commentary or "无",
        }

        system = _safe_format(prompts.COMMENTATOR_SYSTEM, ctx)
        user_msg = _safe_format(prompts.COMMENTATOR_USER, ctx)

        client = core.LLMClient(c.base_url, c.api_key, c.model, timeout_s=self.commentator_timeout_s)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
        if public_only:
            messages[0]["content"] += "\n本场为人机对战：只能依据公开牌面和公开行动解说，不推断、复述或声称知道任何底牌与私有推理。"
        temp = c.temperature
        t_enabled = c.thinking_enabled
        t_budget = c.thinking_budget

        log.info("解说员请求 | event=%s | model=%s", event, c.model)
        log.debug("解说员 messages:\n%s", json.dumps(messages, ensure_ascii=False, indent=2)[:5000])
        match_id, hand_no = self.match_id, self.state.hand_id
        private_comment = not public_only and not self.state.hand_over
        frame_index = len(self._trace.record["frames"]) - 1

        def worker():
            start = _time.monotonic()
            try:
                result = client.chat(messages=messages, temperature=temp,
                                     thinking_enabled=t_enabled, thinking_budget=t_budget,
                                     thinking_param=c.thinking_param)
                text = (result.get("content") or "").strip()
                log.info("解说员响应 | %.2fs | len=%d", _time.monotonic() - start, len(text))
                log.debug("解说员内容: %s", text[:2000])
                if text:
                    self._commentResult.emit(match_id, hand_no, frame_index, text, private_comment)
            except Exception as e:
                log.error("解说员异常 | %.2fs | %s", _time.monotonic() - start, e)
                self._commentError.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_comment_result(self, text: str, match_id=None, hand_no=None, frame_index=None, private=False) -> None:
        match_id = match_id or self.match_id
        hand_no = hand_no or self.state.hand_id
        frame_index = frame_index if frame_index is not None else len(self._trace.record["frames"]) - 1
        line = dict(text=text, frame=frame_index)
        if match_id == self.match_id:
            if hand_no == self.state.hand_id:
                self._trace.record["commentary"].append(line)
            if hand_no in self._records:
                self._records[hand_no]["commentary"].append(line)
                self._save_record(self._records[hand_no])
        elif self.history_store:
            try:
                record = self.history_store.get_hand(match_id, hand_no)
                if record:
                    record["commentary"].append(line)
                    self.history_store.save_hand(self._metadata, record)
            except (OSError, sqlite3.Error) as error:
                self.errorRaised.emit("解说保存失败：" + str(error))
            return
        if private and self.privacy_active and hand_no == self.state.hand_id:
            return
        self.emit_event("commentary", text, private=private)
        self._prev_commentary = text[:200]
        self.commentaryAppended.emit(f"🎙️ {text}")

    def _start_trace(self):
        self._trace = HandTrace(self.match_id, self.state,
                                {p: self._display_name(p) for p in self.state.players},
                                {p: self.profile[p].model for p in self.state.players}, self.model_stats)
        self._trace.record["player_types"] = {
            p: "human" if humans.configured(profile) else "bot" if bots.configured(profile) else "ai"
            for p, profile in self.profile.items()}

    def _save_record(self, record):
        if self.history_store:
            try:
                self.history_store.save_hand(self._metadata, record)
            except (OSError, sqlite3.Error) as error:
                self.errorRaised.emit("牌谱保存失败（对局可继续）：" + str(error))

    def _detect_allin(self):
        captured = self._trace.detect_all_in(self.state) if self._trace else None
        if not captured:
            return
        match_id, hand_no, store = self.match_id, self.state.hand_id, self.history_store
        owner = weakref.ref(self)
        def worker():
            try:
                a, b, tie = equity.calculate_equity(*equity.card_key(tuple(captured["hole"]["AI_A"]),
                    tuple(captured["hole"]["AI_B"]), tuple(captured["board"])))
                result = dict(AI_A=a, AI_B=b, tie=tie)
                if store:
                    store.save_equity(match_id, hand_no, result)
                target = owner()
                if target:
                    target._allinResult.emit(match_id, hand_no, result)
            except (ValueError, OSError, sqlite3.Error, RuntimeError):
                log.exception("全押胜率暂不可用")
        threading.Thread(target=worker, daemon=True).start()

    def _on_allin_equity(self, match_id, hand_no, result):
        if match_id != self.match_id:
            return
        if self._trace and self.state.hand_id == hand_no and self._trace.record["all_in"]:
            self._trace.record["all_in"]["equity"] = result
        if hand_no in self._records:
            self._records[hand_no]["all_in"]["equity"] = result
            self.handCompleted.emit(self._records[hand_no])

    def _handle_comment_error(self, err: str) -> None:
        self.emit_event("warning", "解说暂不可用：" + err[:200])
        self.commentaryAppended.emit(f"⚠️ 解说员出错: {err[:200]}")

    # ─────────────────────────── 工具方法 ───────────────────────────

    def _invalidate_requests(self) -> None:
        self.active_request_id = 0
        self.thinking = False

    def _pause_auto(self, reason: str, error: str | None = None) -> None:
        self.auto_running = False
        self._paused_reason = reason
        self._invalidate_requests()
        if error:
            self.last_error = error
        self._emit_vm()
        if error:
            self.errorRaised.emit(error)

    def _handle_ai_failure(self, player: str, err: str) -> None:
        self.emit_event("warning", err, player)
        self.thinking = False
        self._consecutive_failures += 1
        pname = self._display_name(player)  # type: ignore[arg-type]
        remaining = self.max_consecutive_failures - self._consecutive_failures
        self.last_error = err
        self.logAppended.emit(
            f"[{pname}] 请求失败 (连续第 {self._consecutive_failures} 次，还剩 {max(remaining, 0)} 次机会)"
        )
        self.logAppended.emit(f"[{pname}] 错误: {err[:500]}")

        if self.auto_running and self._consecutive_failures >= self.max_consecutive_failures:
            reason = f"连续 {self._consecutive_failures} 次调用失败，已自动停止"
            self.logAppended.emit(f"■ {reason}")
            self._pause_auto(reason, err)
            return

        self._emit_vm()
        if not self.auto_running:
            self.errorRaised.emit(err)

    def _raise_error(self, msg: str) -> None:
        self.emit_event("warning", msg)
        self.last_error = msg
        self.errorRaised.emit(msg)

    def _compute_action_availability(self) -> ActionAvailability:
        p = self.state.next_to_act
        if not p or self.state.hand_over:
            return ActionAvailability(
                can_fold=False,
                can_check=False,
                can_call=False,
                can_bet=False,
                can_raise=False,
                can_allin=False,
                allin_action=None,
                allin_to_cents=None,
                disabled_reason="当前无需行动",
                to_call_cents=0,
                min_bet_to_cents=None,
                min_raise_to_cents=None,
                max_to_cents=0,
                suggested_to_cents=None,
            )

        legal = self.state.legal_actions(p)
        acts = set(legal.get("actions", []))
        max_to = int(legal.get("max_to_cents", 0))
        stack = int(legal.get("stack_cents", 0))

        allin_action: str | None = None
        allin_to: int | None = None
        if stack > 0:
            if "raise" in acts:
                allin_action = "raise"
                allin_to = max_to
            elif "bet" in acts:
                allin_action = "bet"
                allin_to = max_to
            elif "call" in acts and int(legal.get("to_call_cents", 0)) >= stack:
                allin_action = "call"
                allin_to = None

        return ActionAvailability(
            can_fold=("fold" in acts),
            can_check=("check" in acts),
            can_call=("call" in acts),
            can_bet=("bet" in acts),
            can_raise=("raise" in acts),
            can_allin=allin_action is not None,
            allin_action=allin_action,
            allin_to_cents=allin_to,
            disabled_reason=None,
            to_call_cents=int(legal.get("to_call_cents", 0)),
            min_bet_to_cents=legal.get("min_bet_to_cents"),
            min_raise_to_cents=legal.get("min_raise_to_cents"),
            max_to_cents=max_to,
            suggested_to_cents=legal.get("suggested_to_cents"),
        )

    def _emit_vm(self) -> None:
        s = self.state.get_public_state()
        hole_texts: dict[PlayerID, list[str]] = {
            "AI_A": [core.card_to_text(c) if c is not None else "" for c in s.hole["AI_A"]],
            "AI_B": [core.card_to_text(c) if c is not None else "" for c in s.hole["AI_B"]],
        }
        board_texts = [core.card_to_text(c) if c is not None else "" for c in s.board]
        human = self.human_player
        human_turn = bool(human and s.next_to_act == human and not s.hand_over and not self.thinking)
        if human_turn and not self._human_started:
            self._human_started = _time.monotonic()
        if human and not self.god_view_override:
            if s.win_reason != "showdown":
                opponent = "AI_B" if human == "AI_A" else "AI_A"
                hole_texts[opponent] = ["??" if c else "" for c in s.hole[opponent]]
            if not s.hand_over:
                count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[s.street]
                board_texts = board_texts[:count] + [""] * (5 - count)

        next_to_act = s.next_to_act if s.next_to_act in ("AI_A", "AI_B") else None
        legal = self._compute_action_availability()

        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")

        if s.hand_over:
            status = f"本手结束 · {na}：${core.dollars_from_cents(s.stacks_cents['AI_A'])} · {nb}：${core.dollars_from_cents(s.stacks_cents['AI_B'])}"
        else:
            next_name = self._display_name(next_to_act) if next_to_act else "等待推进"
            street_cn = {"preflop": "翻牌前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}[s.street]
            status = f"底池：${core.dollars_from_cents(s.pot_cents)}  ·  街：{street_cn}  ·  下一位：{next_name}"

        paused_reason = self._paused_reason if not self.auto_running else None
        auto_state = AutoState(
            running=self.auto_running,
            paused_reason=paused_reason,
            auto_fill_missing=self.auto_fill_missing,
            auto_advance_street=self.auto_advance_street,
        )

        vm = AppViewModel(
            hand_id=s.hand_id,
            button=s.button,  # type: ignore[arg-type]
            street=s.street,
            pot_cents=s.pot_cents,
            stacks_cents={"AI_A": s.stacks_cents["AI_A"], "AI_B": s.stacks_cents["AI_B"]},
            hole_cards=hole_texts,
            board_cards=board_texts,
            next_to_act=next_to_act,
            legal=legal,
            status_text=status,
            history_lines=[self.display_text(line) for line in s.action_history],
            hand_over=s.hand_over,
            winner=s.winner,  # type: ignore[arg-type]
            reason=s.win_reason,
            thinking=self.thinking,
            last_error=self.last_error,
            auto_state=auto_state,
            player_names={"AI_A": na, "AI_B": nb},
            contributed_street_cents={
                "AI_A": self.state.contributed_street.get("AI_A", 0),
                "AI_B": self.state.contributed_street.get("AI_B", 0),
            },
            model_stats={p: dict(stats) for p, stats in self.model_stats.items()},
            model_names={p: profile.model for p, profile in self.profile.items()},
            thinking_started=self.thinking_started,
            last_trash_talk=dict(self._last_trash_talk),
            trash_talk_times=dict(self._trash_talk_times),
            last_analysis={p: text for p, text in self._last_analysis.items() if not self.privacy_active or p == human},
            winner_hand_desc=(core.best_hand_desc([c for c in s.hole[s.winner] if c],
                                                  [c for c in s.board if c])
                              if s.winner and s.win_reason == "showdown" else ""),
            best_five=([core.card_to_text(c) for c in core.best_five_cards(
                [c for c in s.hole[s.winner] + s.board if c])]
                       if s.winner and s.win_reason == "showdown" else []),
            pot_won_cents=((sum(self.state.contributed_total.values()) if s.win_reason == "fold"
                            else 2 * min(self.state.contributed_total.values())) if s.hand_over else 0),
            four_color_deck=self.four_color_deck,
            show_equity=self.show_equity and (not human or self.god_view_override),
            human_player=human,
            human_turn=human_turn,
            privacy_active=self.privacy_active,
            god_view=self.god_view_override,
            reduce_motion=self.reduce_motion,
            hands_won=dict(self._match_stats["wins"]),
            total_hands=self._replay_limit or (self.active_rules.hands if self.active_rules.format == "fixed" else 0),
            blind_level=self.active_rules.level(s.hand_id) + 1,
            blinds_text=f"小盲 ${core.dollars_from_cents(s.sb_cents)} / 大盲 ${core.dollars_from_cents(s.bb_cents)}",
            seats_swapped=self.state.replay_swapped,
            match_finished=self.match_finished,
        )
        self.viewModelChanged.emit(vm)
