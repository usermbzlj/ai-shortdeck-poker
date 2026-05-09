import json
import logging
import threading
import time as _time
from dataclasses import dataclass, field
from typing import Literal

from PySide6 import QtCore

import core
import prompts

log = logging.getLogger("poker.ctrl")

PlayerID = Literal["AI_A", "AI_B"]


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


@dataclass
class LLMProfile:
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
        return bool(self.base_url and self.api_key and self.model)


class GameController(QtCore.QObject):
    viewModelChanged = QtCore.Signal(object)
    logAppended = QtCore.Signal(str)
    commentaryAppended = QtCore.Signal(str)
    errorRaised = QtCore.Signal(str)

    _llmResult = QtCore.Signal(int, str, str, str)   # req_id, player, content, reasoning
    _llmError = QtCore.Signal(int, str, str)          # req_id, player, error_msg
    _commentResult = QtCore.Signal(str)               # commentary text
    _commentError = QtCore.Signal(str)
    _reactionResult = QtCore.Signal(str, str)          # player_label, text

    def __init__(self):
        super().__init__()
        self._llmResult.connect(self._handle_llm_result)
        self._llmError.connect(self._handle_llm_error)
        self._commentResult.connect(self._handle_comment_result)
        self._commentError.connect(self._handle_comment_error)
        self._reactionResult.connect(self._handle_reaction_result)
        self.state = core.HandState("AI_A", "AI_B")

        self.profile: dict[PlayerID, LLMProfile] = {"AI_A": LLMProfile(), "AI_B": LLMProfile()}
        self.commentator = CommentatorProfile()

        self._hand_memory: dict[PlayerID, list[dict]] = {"AI_A": [], "AI_B": []}

        self.thinking = False
        self.auto_running = False
        self.auto_fill_missing = True
        self.auto_advance_street = True

        self.request_id = 0
        self.active_request_id = 0
        self.last_error: str | None = None
        self._paused_reason: str | None = None

        self._consecutive_failures = 0
        self.max_consecutive_failures = 3

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

        # WebSocket 观察者（用于向前端牌桌广播）
        self._observers: list[callable] = []

        self._emit_vm()

    def _display_name(self, pid: PlayerID) -> str:
        return self.profile[pid].name or pid

    def add_observer(self, callback: callable) -> None:
        self._observers.append(callback)

    def _notify(self, event_type: str, payload: dict) -> None:
        for cb in self._observers:
            try:
                cb(event_type, payload)
            except Exception as e:
                log.warning("Observer error for %s: %s", event_type, e)

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
        self._emit_vm()

    def set_auto_options(self, fill_missing: bool, auto_advance_street: bool) -> None:
        self.auto_fill_missing = bool(fill_missing)
        self.auto_advance_street = bool(auto_advance_street)
        self._emit_vm()

    def _clear_hand_memory(self) -> None:
        self._hand_memory = {"AI_A": [], "AI_B": []}

    def start_new_match(self, start_stack_cents: int, sb_cents: int, bb_cents: int) -> None:
        log.info("start_new_match | stack=%d | sb=%d | bb=%d", start_stack_cents, sb_cents, bb_cents)
        self._invalidate_requests()
        self.last_error = None
        self._clear_hand_memory()
        self._last_trash_talk = {"AI_A": "", "AI_B": ""}
        self._last_analysis = {"AI_A": "", "AI_B": ""}
        self._match_stats = {"total_hands": 0, "wins": {"AI_A": 0, "AI_B": 0}}
        self._prev_commentary = ""
        self._hand_end_ts = 0.0
        self._pending_reactions = 0
        self.state.sb_cents = sb_cents
        self.state.bb_cents = bb_cents
        self.state.new_match(start_stack_cents)
        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")
        self.logAppended.emit("--- \U0001f195 新比赛开始 ---")
        self.logAppended.emit(f"Stack: ${core.dollars_from_cents(start_stack_cents)} | Blinds: ${core.dollars_from_cents(sb_cents)}/${core.dollars_from_cents(bb_cents)}")
        self.logAppended.emit(f"--- \U0001f0cf Hand #{self.state.hand_id} | Button: {self._display_name(self.state.button)} ---")
        self._notify("match_started", {
            "start_stack_cents": start_stack_cents,
            "sb_cents": sb_cents,
            "bb_cents": bb_cents,
            "player_a": na,
            "player_b": nb,
        })
        self._emit_vm()

    def start_next_hand(self) -> None:
        log.info("start_next_hand")
        self._invalidate_requests()
        self.last_error = None
        self._clear_hand_memory()
        self._last_trash_talk = {"AI_A": "", "AI_B": ""}
        self._last_analysis = {"AI_A": "", "AI_B": ""}
        self.state.start_hand()
        self.logAppended.emit(f"--- \U0001f0cf Hand #{self.state.hand_id} | Button: {self._display_name(self.state.button)} ---")
        self._notify("hand_started", {
            "hand_id": self.state.hand_id,
            "button": self.state.button,
        })
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

    def execute_action(self, action: core.Action, to_cents: int | None) -> None:
        log.info("execute_action (手动) | action=%s | to_cents=%s | next_to_act=%s", action, to_cents, self.state.next_to_act)
        self._invalidate_requests()
        self.last_error = None
        p = self.state.next_to_act
        if not p:
            raise core.UserFacingError("当前无需行动")
        pname = self._display_name(p)
        self.state.apply_action(p, action, to_cents)
        log.debug("execute_action 完成 | hand_over=%s | next_to_act=%s | pot=%d", self.state.hand_over, self.state.next_to_act, self.state.pot_cents)
        self._notify("action_executed", {
            "player": p,
            "player_name": pname,
            "action": action,
            "to_cents": to_cents,
            "manual": True,
        })
        self._emit_vm()

    def advance_street(self) -> None:
        log.info("advance_street 请求 | 当前=%s", self.state.street)
        self._invalidate_requests()
        self.last_error = None
        self.state.advance_street()
        street_name = self.state.street.upper()
        self.logAppended.emit(f"=== 进阶到 {street_name} ===")
        self._trigger_commentary(f"进入 {street_name}")
        self._notify("street_advanced", {"street": self.state.street})
        self._emit_vm()

    def showdown(self) -> None:
        log.info("showdown 请求")
        self._invalidate_requests()
        self.last_error = None
        self.state.resolve_showdown()
        if self.state.winner:
            winner_name = self._display_name(self.state.winner)
            res = f"\U0001f451 摊牌结束! 主池赢家: {winner_name}"
        else:
            res = "\U0001f91d 主池平局 (Split Main Pot)"
        self.logAppended.emit(f"{res} (原因: {self.state.win_reason})")
        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")
        self.logAppended.emit(
            f"\U0001f3e6 结算后 | {na}: ${core.dollars_from_cents(self.state.stacks['AI_A'])} | {nb}: ${core.dollars_from_cents(self.state.stacks['AI_B'])}"
        )
        self._update_match_stats(self.state.winner)
        self._hand_end_ts = _time.monotonic()
        self._trigger_commentary("本手结束 — 摊牌", is_hand_end=True)
        self._trigger_player_reactions()
        self._notify("hand_ended", {
            "winner": self.state.winner,
            "win_reason": self.state.win_reason,
            "winner_name": winner_name if self.state.winner else None,
        })
        self._emit_vm()

    def set_auto_running(self, running: bool) -> None:
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
                self._raise_error(str(e))
                self.auto_running = False
                self._paused_reason = "自动开始下一手失败"
                self._emit_vm()
            return

        if s.next_to_act is None:
            if self.auto_advance_street:
                if s.street == "river":
                    try:
                        self.showdown()
                    except Exception as e:
                        self._raise_error(str(e))
                        self.auto_running = False
                        self._paused_reason = "摊牌失败"
                        self._emit_vm()
                    return
                try:
                    self.advance_street()
                except Exception as e:
                    self._raise_error(str(e))
                    self.auto_running = False
                    self._paused_reason = "推进街失败"
                    self._emit_vm()
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
                self._raise_error(str(e))
                self.auto_running = False
                self._paused_reason = "补牌失败"
                self._emit_vm()
                return

        self.request_ai_decision()

    # ─────────────────────────── AI 决策请求 ───────────────────────────

    def request_ai_decision(self) -> None:
        p = self.state.next_to_act
        if not p:
            return
        if self.thinking:
            return

        self.request_id += 1
        req_id = self.request_id
        self.active_request_id = req_id
        self.thinking = True
        self.last_error = None
        self._emit_vm()

        prof = self.profile[p]
        client = core.LLMClient(prof.base_url, prof.api_key, prof.model, timeout_s=60)
        messages = self._build_llm_messages(p)
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
        self._notify("thinking_started", {"player": p, "player_name": pname, "req_id": req_id})

        def worker():
            start = _time.monotonic()
            try:
                result = client.chat(
                    messages=messages,
                    temperature=temperature,
                    thinking_enabled=thinking_enabled,
                    thinking_budget=thinking_budget,
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
            self._llmResult.emit(req_id, p, content, reasoning)

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
        self.thinking = False
        self._consecutive_failures += 1
        pname = self._display_name(player)  # type: ignore[arg-type]
        remaining = self.max_consecutive_failures - self._consecutive_failures
        self.logAppended.emit(f"[{pname}] 请求失败 (连续第 {self._consecutive_failures} 次，还剩 {max(remaining, 0)} 次机会)")
        self._raise_error(err)
        self._notify("error", {"player": player, "player_name": pname, "error": err})
        if self._consecutive_failures >= self.max_consecutive_failures and self.auto_running:
            self.auto_running = False
            self._paused_reason = f"连续 {self._consecutive_failures} 次调用失败，已自动停止"
            self.logAppended.emit(f"■ {self._paused_reason}")
        self._emit_vm()

    def _handle_llm_result(self, req_id: int, player: str, content: str, reasoning: str) -> None:
        log.debug("_handle_llm_result | req_id=%d | active=%d | player=%s", req_id, self.active_request_id, player)
        if req_id != self.active_request_id:
            log.debug("忽略过期请求 req_id=%d (active=%d)", req_id, self.active_request_id)
            return
        self.thinking = False
        self._consecutive_failures = 0
        pid: PlayerID = player  # type: ignore[assignment]
        pname = self._display_name(pid)
        try:
            # 显示思考过程
            if reasoning:
                short = reasoning[:500] + ("..." if len(reasoning) > 500 else "")
                self.logAppended.emit(f"🧠 [{pname}] 内心思考: {short}")

            decision = core.Decision.from_text(content)
            if decision.analysis:
                self.logAppended.emit(f"\U0001f4a1 [{pname}] 推理: {decision.analysis}")
                self._last_analysis[pid] = decision.analysis[:200]

            if decision.trash_talk:
                self._last_trash_talk[pid] = decision.trash_talk
                self.logAppended.emit(f"🗣️ [{pname} 喊话]: \"{decision.trash_talk}\"")

            # 向前端广播 AI 思考结果
            self._notify("thinking_result", {
                "player": pid,
                "player_name": pname,
                "reasoning": reasoning,
                "analysis": decision.analysis,
                "trash_talk": decision.trash_talk,
            })

            if decision.to_cents is not None:
                legal = self.state.legal_actions(player)
                max_to = legal.get("max_to_cents", 0)
                min_to = legal.get("min_bet_to_cents") or legal.get("min_raise_to_cents") or 1
                # all-in 可以低于最小加注额（德州扑克规则），封顶 min_to
                if max_to > 0 and min_to > max_to:
                    min_to = max_to
                if max_to > 0 and decision.to_cents > max_to:
                    raise core.UserFacingError(
                        f"模型返回的 to_cents={decision.to_cents} 超出最大值 {max_to}"
                        f"（{core.dollars_from_cents(max_to)} USD）。"
                        "请检查模型是否把单位误用为[元]而非[分]。"
                    )
                if decision.to_cents < min_to:
                    raise core.UserFacingError(
                        f"模型返回的 to_cents={decision.to_cents} 小于最小值 {min_to}"
                        f"（{core.dollars_from_cents(min_to)} USD）。"
                    )

            # 存入记忆（user 消息 + assistant 回复）
            prof = self.profile[pid]
            if prof.memory_enabled:
                msgs = self._build_llm_messages(pid)
                last_user = msgs[-1]
                self._hand_memory[pid].append(last_user)
                self._hand_memory[pid].append({"role": "assistant", "content": content})

            # 在 apply_action 之前保存底池快照（fold 会立即清零 pot）
            pot_before = self.state.pot_cents

            self.state.apply_action(player, decision.action, decision.to_cents)
            action_line = f"\U0001f449 {pname} 决定: {decision.action.upper()}"
            if decision.to_cents is not None:
                action_line += f" to ${core.dollars_from_cents(decision.to_cents)}"
            self.logAppended.emit(action_line)

            # 向前端广播动作执行
            self._notify("action_executed", {
                "player": pid,
                "player_name": pname,
                "action": decision.action,
                "to_cents": decision.to_cents,
            })

            if self.state.hand_over and self.state.win_reason == "fold":
                winner_name = self._display_name(self.state.winner) if self.state.winner else "?"
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
            self._raise_error(str(e))
        self._emit_vm()

    # ─────────────────────────── 比赛统计 ──────────────────────────

    def _update_match_stats(self, winner: str | None) -> None:
        self._match_stats["total_hands"] += 1
        if winner in ("AI_A", "AI_B"):
            self._match_stats["wins"][winner] += 1

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
        """手牌结束后向双方 AI 各发一次请求，获取心理活动或赛后感想。"""
        common = self._build_reaction_common_ctx()
        s = common["s"]
        na, nb = common["na"], common["nb"]

        if is_match_end:
            final_stacks = f"{na}: ${core.dollars_from_cents(s.stacks_cents['AI_A'])} | {nb}: ${core.dollars_from_cents(s.stacks_cents['AI_B'])}"
            loser = "AI_A" if s.stacks_cents["AI_A"] <= 0 else "AI_B"
            winner = "AI_B" if loser == "AI_A" else "AI_A"
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
        if not prof.base_url or not prof.api_key or not prof.model:
            return
        self._pending_reactions += 1
        text = _safe_format(template, ctx)
        client = core.LLMClient(prof.base_url, prof.api_key, prof.model, timeout_s=30)
        messages = [{"role": "user", "content": text}]
        temp = prof.temperature
        t_enabled = prof.thinking_enabled
        t_budget = prof.thinking_budget

        def worker():
            try:
                result = client.chat(messages=messages, temperature=temp,
                                     thinking_enabled=t_enabled, thinking_budget=t_budget)
                content = (result.get("content") or "").strip()
                if content:
                    self._reactionResult.emit(label, content)
                    self._notify("player_reaction", {"player": pid, "label": label, "text": content})
                else:
                    self._reactionResult.emit(label, "")
            except Exception as e:
                log.warning("选手反应请求失败 | %s | %s", label, e)
                self._reactionResult.emit(label, "")

        threading.Thread(target=worker, daemon=True).start()

    def _handle_reaction_result(self, label: str, text: str) -> None:
        self._pending_reactions = max(0, self._pending_reactions - 1)
        if text:
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
        if is_action and not c.on_action:
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
        if c.god_view:
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
            a_text = self._last_analysis.get(pid_key, "")
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
            "prev_commentary": self._prev_commentary or "无",
        }

        system = _safe_format(prompts.COMMENTATOR_SYSTEM, ctx)
        user_msg = _safe_format(prompts.COMMENTATOR_USER, ctx)

        client = core.LLMClient(c.base_url, c.api_key, c.model, timeout_s=30)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
        temp = c.temperature
        t_enabled = c.thinking_enabled
        t_budget = c.thinking_budget

        log.info("解说员请求 | event=%s | model=%s", event, c.model)
        log.debug("解说员 messages:\n%s", json.dumps(messages, ensure_ascii=False, indent=2)[:5000])

        def worker():
            start = _time.monotonic()
            try:
                result = client.chat(messages=messages, temperature=temp,
                                     thinking_enabled=t_enabled, thinking_budget=t_budget)
                text = (result.get("content") or "").strip()
                log.info("解说员响应 | %.2fs | len=%d", _time.monotonic() - start, len(text))
                log.debug("解说员内容: %s", text[:2000])
                if text:
                    self._commentResult.emit(text)
                    self._notify("commentary", {"text": text, "event": event})
            except Exception as e:
                log.error("解说员异常 | %.2fs | %s", _time.monotonic() - start, e)
                self._commentError.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_comment_result(self, text: str) -> None:
        self._prev_commentary = text[:200]
        self.commentaryAppended.emit(f"🎙️ {text}")

    def _handle_comment_error(self, err: str) -> None:
        self.commentaryAppended.emit(f"⚠️ 解说员出错: {err[:200]}")

    # ─────────────────────────── 工具方法 ───────────────────────────

    def _invalidate_requests(self) -> None:
        self.active_request_id = 0
        self.thinking = False

    def _raise_error(self, msg: str) -> None:
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

        next_to_act = s.next_to_act if s.next_to_act in ("AI_A", "AI_B") else None
        legal = self._compute_action_availability()

        na = self._display_name("AI_A")
        nb = self._display_name("AI_B")

        if s.hand_over:
            status = f"\U0001f3c1 本手结束 | Pot: $0.00 | {na}: ${core.dollars_from_cents(s.stacks_cents['AI_A'])} | {nb}: ${core.dollars_from_cents(s.stacks_cents['AI_B'])}"
        else:
            next_name = self._display_name(next_to_act) if next_to_act else "(none)"
            status = f"Pot: ${core.dollars_from_cents(s.pot_cents)} | Street: {s.street} | Next: {next_name}"

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
            history_lines=list(s.action_history),
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
        )
        self.viewModelChanged.emit(vm)
        # 向前端牌桌广播完整状态
        self._notify("state_sync", {
            "hand_id": vm.hand_id,
            "street": vm.street,
            "button": vm.button,
            "pot_cents": vm.pot_cents,
            "stacks_cents": vm.stacks_cents,
            "hole_cards": vm.hole_cards,
            "board_cards": vm.board_cards,
            "next_to_act": vm.next_to_act,
            "hand_over": vm.hand_over,
            "winner": vm.winner,
            "win_reason": vm.reason,
            "thinking": vm.thinking,
            "last_error": vm.last_error,
            "player_names": vm.player_names,
            "contributed_street_cents": vm.contributed_street_cents,
            "action_history": vm.history_lines,
            "status_text": vm.status_text,
        })
