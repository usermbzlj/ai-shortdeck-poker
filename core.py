import json
import logging
import os
import random
import time as _time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
from typing import Literal

import httpx

log = logging.getLogger("poker")


def _mask_key(key: str) -> str:
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"


def setup_logging(enabled: bool, base_dir: str | None = None) -> None:
    """初始化 debug 日志。enabled=False 时仅保留 WARNING 以上级别。"""
    logger = logging.getLogger("poker")
    for old_handler in logger.handlers:
        old_handler.close()
    logger.handlers.clear()
    logger.propagate = False

    if not enabled:
        logger.setLevel(logging.WARNING)
        logger.addHandler(logging.NullHandler())
        return

    logger.setLevel(logging.DEBUG)
    log_dir = os.path.join(base_dir or os.path.dirname(__file__), "log")
    os.makedirs(log_dir, exist_ok=True)

    filename = f"debug_{datetime.now().strftime('%Y-%m-%d')}.log"
    filepath = os.path.join(log_dir, filename)

    handler = logging.FileHandler(filepath, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.info("=== Debug 日志已启用，写入: %s ===", filepath)


RANK_TO_CHAR = {6: "6", 7: "7", 8: "8", 9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
CHAR_TO_RANK = {v: k for k, v in RANK_TO_CHAR.items()}
SUITS = ("s", "h", "d", "c")

SUIT_CN = {"s": "黑桃", "h": "红心", "d": "方块", "c": "梅花"}
RANK_CN = {6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}

HAND_RANK_NAMES = {
    0: "高牌", 1: "一对", 2: "两对", 3: "三条",
    4: "顺子", 5: "葫芦", 6: "同花", 7: "四条", 8: "同花顺",
}

Street = Literal["preflop", "flop", "turn", "river"]
Action = Literal["fold", "check", "call", "bet", "raise"]
Card = tuple[int, str]


class UserFacingError(Exception):
    pass


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def dollars_from_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def cents_from_dollars_text(text: str) -> int:
    t = (text or "").strip()
    if not t:
        raise UserFacingError("金额不能为空")
    try:
        d = Decimal(t)
    except InvalidOperation as e:
        raise UserFacingError(f"无法解析金额：{t}") from e
    cents = int((d * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents


def cents_from_dollars_float(dollars: float) -> int:
    return int(round(dollars * 100))


def parse_card(text: str) -> Card:
    t = (text or "").strip()
    if len(t) != 2:
        raise UserFacingError(f"牌格式应为两字符，如 Ah、Td、6s：{t}")
    r = t[0].upper()
    s = t[1].lower()
    if r not in CHAR_TO_RANK:
        raise UserFacingError(f"无效点数：{r}")
    if s not in SUITS:
        raise UserFacingError(f"无效花色：{s}")
    rank = CHAR_TO_RANK[r]
    if rank < 6:
        raise UserFacingError(f"短牌只允许 6-A：{t}")
    return rank, s


def card_to_text(card: Card) -> str:
    r, s = card
    return f"{RANK_TO_CHAR[r]}{s}"


def card_to_chinese(card_text: str) -> str:
    """'Ah' → '红心A', 'Td' → '方块10'。空串/无效返回原文。"""
    if not card_text or len(card_text) < 2:
        return card_text
    rank_c = card_text[0].upper()
    suit_c = card_text[1].lower()
    rank_val = CHAR_TO_RANK.get(rank_c)
    if rank_val is None or suit_c not in SUIT_CN:
        return card_text
    return f"{SUIT_CN[suit_c]}{RANK_CN[rank_val]}"


def all_short_deck_texts() -> list[str]:
    return [f"{RANK_TO_CHAR[r]}{s}" for r in range(6, 15) for s in SUITS]


def build_short_deck() -> list[Card]:
    return [(r, s) for r in range(6, 15) for s in SUITS]


def is_straight_short_deck(ranks: list[int]) -> tuple[bool, int]:
    uniq = sorted(set(ranks), reverse=True)
    if len(uniq) < 5:
        return False, 0
    if {14, 6, 7, 8, 9}.issubset(set(uniq)):
        return True, 9
    for i in range(len(uniq) - 4):
        window = uniq[i : i + 5]
        if window[0] - window[4] == 4 and len(set(window)) == 5:
            return True, window[0]
    return False, 0


def evaluate_5(cards: list[Card]) -> tuple:
    ranks = [r for r, _ in cards]
    suits = [s for _, s in cards]
    ranks_desc = sorted(ranks, reverse=True)
    counts = {r: ranks.count(r) for r in ranks}
    items = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    is_flush = len(set(suits)) == 1
    straight, straight_high = is_straight_short_deck(ranks)

    if straight and is_flush:
        return (8, straight_high)
    if items[0][1] == 4:
        return (7, items[0][0], max(r for r in ranks if r != items[0][0]))
    if items[0][1] == 3 and items[1][1] == 2:
        return (5, items[0][0], items[1][0])
    if is_flush:
        return (6, ranks_desc)
    if straight:
        return (4, straight_high)
    if items[0][1] == 3:
        return (3, items[0][0], sorted([r for r in ranks if r != items[0][0]], reverse=True))
    if items[0][1] == 2 and items[1][1] == 2:
        return (
            (2, max(items[0][0], items[1][0]), min(items[0][0], items[1][0]), max(r for r in ranks if r not in (items[0][0], items[1][0])))
        )
    if items[0][1] == 2:
        return (1, items[0][0], sorted([r for r in ranks if r != items[0][0]], reverse=True))
    return (0, ranks_desc)


def best_hand_rank_7(cards7: list[Card]) -> tuple:
    return max(evaluate_5(list(comb)) for comb in combinations(cards7, 5))


def best_five_cards(cards: list[Card]) -> list[Card]:
    if len(cards) < 5:
        return []
    if len(set(cards)) != len(cards):
        raise ValueError("最佳五张牌中存在重复牌")
    return list(max(combinations(cards, 5), key=lambda hand: evaluate_5(list(hand))))


def describe_hand_rank(rank_tuple: tuple) -> str:
    return HAND_RANK_NAMES.get(rank_tuple[0], "未知")


def best_hand_desc(hole: list[Card], board: list[Card]) -> str:
    """根据已知牌计算当前最佳牌型中文描述。牌不足 5 张时返回空串。"""
    all_cards = hole + board
    if len(all_cards) < 5:
        return ""
    rank = max(evaluate_5(list(c)) for c in combinations(all_cards, 5))
    return describe_hand_rank(rank)


@dataclass(frozen=True)
class Decision:
    action: Action
    to_cents: int | None
    analysis: str
    trash_talk: str
    raw: dict

    @staticmethod
    def from_text(text: str, allow_nonpositive: bool = False) -> "Decision":
        log.debug("Decision.from_text 原始文本 (%d字):\n%s", len(text), text[:3000])
        obj = parse_first_json_object(text)
        log.debug("Decision 解析出 JSON: %s", json.dumps(obj, ensure_ascii=False)[:2000])
        action_raw = str(obj.get("action", "")).strip().lower()
        if action_raw not in ("fold", "check", "call", "bet", "raise"):
            raise UserFacingError(f"模型返回非法 action：{action_raw}")
        action: Action = action_raw  # type: ignore[assignment]

        analysis = str(obj.get("analysis", "")).strip()
        trash_talk = str(obj.get("trash_talk", "")).strip()

        to_cents: int | None = None
        if action in ("bet", "raise"):
            if "to_cents" in obj and obj.get("to_cents") is not None:
                to_cents = parse_int(obj.get("to_cents"))
            elif "to_usd" in obj and obj.get("to_usd") is not None and str(obj.get("to_usd")).strip():
                to_cents = cents_from_dollars_text(str(obj.get("to_usd")))
            else:
                raise UserFacingError("模型返回缺少 to_cents/to_usd（bet/raise 必填）")
            if to_cents <= 0 and not allow_nonpositive:
                raise UserFacingError("模型返回的 to_cents 必须为正整数")
        log.info("Decision 解析结果: action=%s, to_cents=%s, trash_talk=%s", action, to_cents, bool(trash_talk))
        return Decision(action=action, to_cents=to_cents, analysis=analysis, trash_talk=trash_talk, raw=obj)


def parse_int(v) -> int:
    if isinstance(v, bool):
        raise UserFacingError("金额字段类型错误")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if int(v) != v:
            raise UserFacingError("金额字段必须为整数 cents")
        return int(v)
    s = str(v).strip()
    if not s:
        raise UserFacingError("金额字段为空")
    try:
        return int(s)
    except ValueError as e:
        raise UserFacingError(f"无法解析整数：{s}") from e


def strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if not lines:
        return t
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_first_json_object(text: str) -> dict:
    t = strip_code_fences(text)
    if not t:
        raise UserFacingError("模型返回为空")
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(t[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise UserFacingError("未能从模型输出中解析出 JSON 对象")


class LLMClient:
    @staticmethod
    def _http_error(status: int, detail: str) -> str:
        lower = detail.lower()
        if status == 402 or "insufficient balance" in lower or "insufficient_balance" in lower:
            friendly = "账户余额不足"
        elif status in (401, 403):
            friendly = "API Key 无效或无权限"
        elif status == 404:
            friendly = "模型或 API 路径不存在，请检查 Model 和 Base URL"
        elif status == 429:
            friendly = "触发限流，请稍后重试"
        elif status >= 500:
            friendly = "服务端错误，请稍后重试"
        else:
            friendly = "API 请求失败"
        tail = detail.strip().replace("\n", " ")[-120:]
        return f"{friendly}（HTTP {status}）" + (f"：{tail}" if tail else "")

    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: int = 90):
        self.base_url = (base_url or "").strip()
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_s = timeout_s

    def _candidate_urls(self) -> list[str]:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return [base]
        if base.endswith("/v1"):
            return [f"{base}/chat/completions"]
        return [f"{base}/v1/chat/completions", f"{base}/chat/completions"]

    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        thinking_enabled: bool = False,
        thinking_budget: int = 8000,
        thinking_param: bool = True,
    ) -> dict:
        """返回 {"content": str, "reasoning_content": str|None}"""
        if not self.base_url or not self.api_key or not self.model:
            raise UserFacingError("LLM API 配置不完整 (URL, Key, Model 必填)")

        payload: dict = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if thinking_param and thinking_enabled:
            payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif thinking_param:
            payload["thinking"] = {"type": "disabled"}
        log.debug(
            "LLM 请求准备 | model=%s | base=%s | key=%s | temp=%s | thinking=%s",
            self.model, self.base_url, _mask_key(self.api_key), temperature, thinking_enabled,
        )
        log.debug("LLM 请求体:\n%s", json.dumps(payload, ensure_ascii=False, indent=2)[:8000])

        last_http_status = None
        last_http_body = None
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        t0 = _time.monotonic()
        with httpx.Client(timeout=self.timeout_s) as client:
            for url in self._candidate_urls():
                log.debug("LLM 尝试 URL: %s", url)
                try:
                    resp = client.post(url, headers=headers, json=payload)
                except httpx.TimeoutException as e:
                    log.debug("LLM 请求超时", exc_info=True)
                    raise UserFacingError(f"请求超时({self.timeout_s}s)：请检查网络或增大超时时间") from e
                except httpx.RequestError as e:
                    log.error("LLM 网络错误: %s (%.2fs)", e, _time.monotonic() - t0)
                    raise UserFacingError(f"网络连接失败：{e}") from e
                elapsed = _time.monotonic() - t0
                log.debug("LLM 响应 | URL=%s | status=%d | %.2fs", url, resp.status_code, elapsed)
                if resp.status_code in (404, 405):
                    last_http_status = resp.status_code
                    last_http_body = resp.text
                    log.debug("LLM URL 不可用 (%d)，尝试下一个", resp.status_code)
                    continue
                if resp.status_code >= 400:
                    log.error("LLM HTTP 错误 %d: %s", resp.status_code, resp.text[:2000])
                    raise UserFacingError(self._http_error(resp.status_code, resp.text))
                data = resp.json()
                log.debug("LLM 响应体:\n%s", json.dumps(data, ensure_ascii=False, indent=2)[:8000])
                msg = data["choices"][0]["message"]
                content = msg.get("content", "")
                reasoning = msg.get("reasoning_content")
                log.info(
                    "LLM 成功 | model=%s | %.2fs | content_len=%d | reasoning_len=%d",
                    self.model, elapsed, len(content), len(reasoning or ""),
                )
                return {"content": content, "reasoning_content": reasoning}
        log.error("LLM 所有 URL 均失败 | last_status=%s", last_http_status)
        raise UserFacingError(self._http_error(last_http_status or 404, last_http_body or ""))


@dataclass
class PublicState:
    hand_id: int
    button: str
    street: Street
    sb_cents: int
    bb_cents: int
    pot_cents: int
    stacks_cents: dict[str, int]
    in_hand: dict[str, bool]
    hole: dict[str, list[Card | None]]
    board: list[Card | None]
    next_to_act: str | None
    action_history: list[str]
    hand_over: bool
    winner: str | None
    win_reason: str | None


class HandState:
    def __init__(self, player_a: str = "AI_A", player_b: str = "AI_B"):
        self.players = (player_a, player_b)
        self.sb_cents = 250
        self.bb_cents = 500
        self.start_stack_cents = 100000
        self.match_seed = random.SystemRandom().randrange(2 ** 63)
        self.deck_sequence = []
        self.replay_swapped = False
        self._hand_order = build_short_deck()

        self.hand_id = 0
        self.button = player_a
        self.stacks: dict[str, int] = {p: self.start_stack_cents for p in self.players}

        self._new_hand_structures()
        # 不在此处自动开局；由 MainWindow 加载完 .env 配置后用正确的值调用 new_match。

    def other(self, p: str) -> str:
        return self.players[1] if p == self.players[0] else self.players[0]

    def sb_player(self) -> str:
        return self.button

    def bb_player(self) -> str:
        return self.other(self.button)

    def new_match(self, start_stack_cents: int | None = None, *, seed=None,
                  deck_sequence=None, swap_seats=False) -> None:
        if start_stack_cents is not None:
            self.start_stack_cents = start_stack_cents
        self.hand_id = 0
        self.match_seed = seed if seed is not None else random.SystemRandom().randrange(2 ** 63)
        self.deck_sequence = [list(deck) for deck in deck_sequence] if deck_sequence is not None else []
        if any(len(deck) != 36 or set(deck) != set(build_short_deck()) for deck in self.deck_sequence):
            raise UserFacingError("复赛牌序必须包含完整且不重复的 36 张牌")
        self.replay_swapped = swap_seats
        self.button = self.players[1] if swap_seats else self.players[0]
        self.stacks = {p: self.start_stack_cents for p in self.players}
        log.info("新比赛 | stack=%d | sb=%d | bb=%d", self.start_stack_cents, self.sb_cents, self.bb_cents)
        self.start_hand()

    def _new_hand_structures(self) -> None:
        self.street: Street = "preflop"
        self.deck: list[Card] = []

        self.in_hand: dict[str, bool] = {p: True for p in self.players}
        self.hole: dict[str, list[Card | None]] = {p: [None, None] for p in self.players}
        self.board: list[Card | None] = [None, None, None, None, None]

        self.locked_hole: dict[str, list[Card | None]] = {p: [None, None] for p in self.players}
        self.locked_board: list[Card | None] = [None, None, None, None, None]

        self.action_history: list[str] = []
        self.pot_cents = 0
        self.contributed_street: dict[str, int] = {p: 0 for p in self.players}
        self.contributed_total: dict[str, int] = {p: 0 for p in self.players}

        self.current_bet_cents = 0
        self.last_full_raise_size_cents = self.bb_cents
        self.can_raise: dict[str, bool] = {p: True for p in self.players}
        self.acted: dict[str, bool] = {p: False for p in self.players}
        self.next_to_act: str | None = None

        self.hand_over = False
        self.winner: str | None = None
        self.win_reason: str | None = None

    def start_hand(self) -> None:
        self.hand_id += 1
        if self.hand_id > 1:
            self.button = self.other(self.button)

        self._new_hand_structures()
        self.street = "preflop"
        if self.hand_id > len(self.deck_sequence):
            deck = build_short_deck()
            random.Random(f"{self.match_seed}:{self.hand_id}").shuffle(deck)
            self.deck_sequence.append(deck)
        self._hand_order = list(self.deck_sequence[self.hand_id - 1])
        self._rebuild_deck()

        self.post_blinds()
        # 不在此处自动发牌，留出窗口让用户指定底牌/公共牌；
        # 实际发牌在 auto_tick（自动补齐）或用户手动点"随机补齐缺牌"时触发。

        log.info(
            "Hand #%d 开始 | button=%s | stacks=%s（底牌待发/指定）",
            self.hand_id, self.button,
            {p: self.stacks[p] for p in self.players},
        )

    def _validate_no_duplicates(self) -> None:
        cards: list[Card] = []
        for p in self.players:
            cards += [c for c in self.hole[p] if c is not None]
        cards += [c for c in self.board if c is not None]
        if len(set(cards)) != len(cards):
            raise UserFacingError("牌面存在重复牌")

    def _rebuild_deck(self) -> None:
        used: set[Card] = set()
        for p in self.players:
            for c in self.hole[p]:
                if c is not None:
                    used.add(c)
        for c in self.board:
            if c is not None:
                used.add(c)
        self.deck = [c for c in reversed(self._hand_order) if c not in used]

    def _seat_order(self):
        return self.players[::-1] if self.replay_swapped else self.players

    def lock_cards(
        self,
        hole_a: list[Card | None] | None,
        hole_b: list[Card | None] | None,
        board_prefix: list[Card | None] | None,
    ) -> None:
        hole_a = hole_a or [None, None]
        hole_b = hole_b or [None, None]
        board_prefix = board_prefix or []

        if len(hole_a) != 2 or len(hole_b) != 2:
            raise UserFacingError("底牌必须是 2 张")
        if len(board_prefix) > 5:
            raise UserFacingError("公共牌最多 5 张")

        next_locked_hole = {self.players[0]: [hole_a[0], hole_a[1]], self.players[1]: [hole_b[0], hole_b[1]]}
        next_locked_board = [None, None, None, None, None]
        for i, c in enumerate(board_prefix):
            next_locked_board[i] = c

        locked_cards: list[Card] = []
        for p in self.players:
            for c in next_locked_hole[p]:
                if c is not None:
                    locked_cards.append(c)
        for c in next_locked_board:
            if c is not None:
                locked_cards.append(c)
        if len(set(locked_cards)) != len(locked_cards):
            raise UserFacingError("锁定牌存在重复")

        for p in self.players:
            for i in range(2):
                locked = next_locked_hole[p][i]
                existing = self.hole[p][i]
                if existing is not None and locked is not None and existing != locked:
                    raise UserFacingError("已发牌后不能更改该位置的牌，请开始新手牌")

        for i in range(5):
            locked = next_locked_board[i]
            existing = self.board[i]
            if existing is not None and locked is not None and existing != locked:
                raise UserFacingError("已发牌后不能更改该位置的牌，请开始新手牌")

        self.locked_hole = next_locked_hole
        self.locked_board = next_locked_board
        for p in self.players:
            for i, c in enumerate(self.locked_hole[p]):
                if c is not None:
                    self.hole[p][i] = c
        for i, c in enumerate(self.locked_board):
            if c is not None:
                self.board[i] = c

        self._validate_no_duplicates()
        slots = [(i * 2 + j, card) for i, p in enumerate(self._seat_order())
                 for j, card in enumerate(self.hole[p]) if card is not None]
        slots += [(4 + i, card) for i, card in enumerate(self.board) if card is not None]
        for slot, card in slots:
            position = self._hand_order.index(card)
            self._hand_order[slot], self._hand_order[position] = card, self._hand_order[slot]
        if self.hand_id:
            self.deck_sequence[self.hand_id - 1] = list(self._hand_order)
        self._rebuild_deck()

    def ensure_dealt(self, street: Street) -> None:
        log.debug("ensure_dealt | street=%s", street)
        need_board = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street]

        for seat, p in enumerate(self._seat_order()):
            for i in range(2):
                if self.hole[p][i] is None:
                    self.hole[p][i] = self._hand_order[seat * 2 + i]

        for i in range(need_board):
            if self.board[i] is None:
                self.board[i] = self._hand_order[4 + i]

        self._validate_no_duplicates()
        self._rebuild_deck()

    def _post(self, p: str, amount: int) -> None:
        pay = min(amount, self.stacks[p])
        self.stacks[p] -= pay
        self.pot_cents += pay
        self.contributed_street[p] += pay
        # contributed_total 记录本手牌内累计投入，仅用于 showdown 边池计算，
        # 不与 pot_cents 同步（fold 结算后 pot_cents 归零但 contributed_total 不变）。
        self.contributed_total[p] += pay

    def post_blinds(self) -> None:
        sb, bb = self.sb_player(), self.bb_player()
        self._post(sb, self.sb_cents)
        self._post(bb, self.bb_cents)

        self.current_bet_cents = self.bb_cents
        self.last_full_raise_size_cents = self.bb_cents

        self.next_to_act = sb
        self.action_history.append(
            f"翻牌前：{sb} 下小盲 ${dollars_from_cents(self.sb_cents)}，{bb} 下大盲 ${dollars_from_cents(self.bb_cents)}"
        )

    def to_call_cents(self, p: str) -> int:
        # 正常情况：当前最大下注 - 本街已投入
        # SB=BB 场景：contributed_street[SB] == current_bet_cents，算出来是 0，
        # 但 SB 尚未行动，仍需补齐至 current_bet_cents（实际补 0，call 等于 check）。
        # 此处返回真实补齐量，让 acted 状态驱动 legal_actions 正确分支。
        return max(0, self.current_bet_cents - self.contributed_street[p])

    def legal_actions(self, p: str) -> dict:
        if self.hand_over or not self.in_hand[p]:
            return {"actions": []}

        to_call = self.to_call_cents(p)
        stack = self.stacks[p]

        # 判断是否 facing_bet：
        # 1. 如果需要补齐金额 (to_call > 0) → facing_bet
        # 2. 如果不需要补齐，但有下注额且没行动过 → 只有当玩家投入 < 当前下注额时才算 facing_bet
        if to_call > 0:
            facing_bet = True
        elif self.current_bet_cents > 0 and not self.acted[p]:
            # 关键修复：只有当玩家投入少于当前下注额时，才需要 facing_bet
            # 如果双方投入相等，即使没 acted 也可以 check
            facing_bet = (self.contributed_street[p] < self.current_bet_cents)
        else:
            facing_bet = False

        actions: list[str] = []
        if facing_bet:
            actions += ["fold", "call"]
        else:
            actions += ["check"]

        max_to = self.contributed_street[p] + stack

        if stack > 0 and self.can_raise[p]:
            if self.current_bet_cents > 0:
                if max_to > self.current_bet_cents:
                    actions.append("raise")
            else:
                actions.append("bet")

        effective_to_call = max(to_call, self.current_bet_cents - self.contributed_street[p]) if facing_bet else 0
        effective_to_call = max(0, effective_to_call)

        min_bet_to = self.bb_cents if self.current_bet_cents == 0 else None
        min_raise_to = self.current_bet_cents + self.last_full_raise_size_cents

        suggested_to = None
        if facing_bet:
            suggested_to = self.current_bet_cents
        elif "raise" in actions:
            suggested_to = min_raise_to
        elif "bet" in actions:
            suggested_to = min_bet_to

        return {
            "actions": actions,
            "to_call_cents": effective_to_call,
            "stack_cents": stack,
            "min_bet_to_cents": min_bet_to,
            "min_raise_to_cents": min_raise_to,
            "max_to_cents": max_to,
            "suggested_to_cents": suggested_to,
        }

    def apply_action(self, p: str, act: Action, to_cents: int | None) -> None:
        log.debug(
            "apply_action | player=%s | action=%s | to_cents=%s | street=%s | pot=%d | stacks=%s | contributed_street=%s",
            p, act, to_cents, self.street, self.pot_cents, dict(self.stacks), dict(self.contributed_street),
        )
        if self.hand_over or p != self.next_to_act:
            raise UserFacingError("非法状态或非当前行动玩家")

        legal = self.legal_actions(p)
        if act not in legal["actions"]:
            raise UserFacingError(f"非法动作：{act}。允许的动作：{legal['actions']}")

        opp = self.other(p)
        street_cn = {"preflop": "翻牌前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}[self.street]
        action_cn = {"fold": "弃牌", "check": "过牌", "call": "跟注", "bet": "下注", "raise": "加注"}[act]
        history_str = f"[{street_cn}] {p} {action_cn}"
        self.acted[p] = True

        if act == "fold":
            self.in_hand[p] = False
            self.hand_over = True
            self.winner, self.win_reason = opp, "fold"
            self.stacks[opp] += self.pot_cents
            self.pot_cents = 0
            self.next_to_act = None
            self.action_history.append(history_str)
            return

        if act == "check":
            self.action_history.append(history_str)
            self.next_to_act = opp
            self._maybe_end_street()
            return

        if act == "call":
            pay = min(self.to_call_cents(p), self.stacks[p])
            self._post(p, pay)
            self.action_history.append(history_str + (f" ${dollars_from_cents(pay)}" if pay > 0 else ""))
            self.next_to_act = opp
            if self.stacks[p] == 0 or self.stacks[opp] == 0:
                self.next_to_act = None
            self._maybe_end_street()
            if self.next_to_act is None and not self.hand_over:
                self._settle_excess()
            return

        if to_cents is None or to_cents <= self.contributed_street[p]:
            raise UserFacingError("bet/raise 的目标金额无效")

        target = min(to_cents, self.contributed_street[p] + self.stacks[p])
        add = target - self.contributed_street[p]
        is_all_in = (add == self.stacks[p])

        if act == "bet":
            min_bet_to = legal["min_bet_to_cents"] or self.bb_cents
            if target < min_bet_to and not is_all_in:
                raise UserFacingError(f"下注额度不足，最小需到 ${dollars_from_cents(min_bet_to)}")

            self.current_bet_cents = target
            self.last_full_raise_size_cents = target
            self._post(p, add)
            self.can_raise[opp] = True

            self.action_history.append(f"{history_str} 至 ${dollars_from_cents(target)}" + ("（全押）" if is_all_in else ""))
            self.next_to_act = opp
            if self.stacks[opp] == 0:
                self.next_to_act = None
            if self.next_to_act is None and not self.hand_over:
                self._settle_excess()
            return

        if act == "raise":
            prev_bet = self.current_bet_cents
            raise_size = target - prev_bet
            min_raise_to = legal["min_raise_to_cents"]

            if target < min_raise_to and not is_all_in:
                raise UserFacingError(f"加注额度不足，最小需到 ${dollars_from_cents(min_raise_to)}")

            is_full_raise = raise_size >= self.last_full_raise_size_cents
            self.current_bet_cents = target
            self._post(p, add)

            if is_full_raise:
                self.last_full_raise_size_cents = raise_size
                self.can_raise[opp] = True
            else:
                self.can_raise[opp] = (not self.acted[opp])

            self.action_history.append(f"{history_str} 至 ${dollars_from_cents(target)}" + ("（全押）" if is_all_in else ""))
            self.next_to_act = opp
            if self.stacks[opp] == 0:
                self.next_to_act = None
            if self.next_to_act is None and not self.hand_over:
                self._settle_excess()
            return

        raise UserFacingError(f"未知动作：{act}")

    def _maybe_end_street(self) -> None:
        a, b = self.players
        if self.contributed_street[a] == self.contributed_street[b] and self.acted[a] and self.acted[b]:
            self.next_to_act = None

    def _settle_excess(self) -> None:
        """当双方投入不对等且劣势方已 all-in 时，立即退还差额。"""
        a, b = self.players
        if not self.in_hand[a] or not self.in_hand[b]:
            return
        total_a, total_b = self.contributed_total[a], self.contributed_total[b]
        if total_a == total_b:
            return
        over, under = (a, b) if total_a > total_b else (b, a)
        if self.stacks[under] > 0:
            return
        excess = abs(total_a - total_b)
        self.stacks[over] += excess
        self.pot_cents -= excess
        self.contributed_total[over] -= excess
        refund_street = min(excess, self.contributed_street[over])
        self.contributed_street[over] -= refund_street
        log.info(
            "_settle_excess | 退还 %s %d 分 | pot=%d | stacks=%s",
            over, excess, self.pot_cents, dict(self.stacks),
        )

    def advance_street(self) -> None:
        if self.hand_over or self.next_to_act is not None:
            raise UserFacingError("不能推进阶段")

        streets: list[Street] = ["preflop", "flop", "turn", "river"]
        idx = streets.index(self.street)
        if idx == len(streets) - 1:
            raise UserFacingError("已到河牌，不能再推进。请摊牌。")
        old_street = self.street
        self.street = streets[idx + 1]
        log.info("advance_street | %s → %s | pot=%d", old_street, self.street, self.pot_cents)

        for p in self.players:
            self.contributed_street[p] = 0
            self.acted[p] = False
            self.can_raise[p] = True

        self.current_bet_cents = 0
        self.last_full_raise_size_cents = self.bb_cents

        if self.stacks[self.players[0]] > 0 and self.stacks[self.players[1]] > 0:
            self.next_to_act = self.bb_player()
        else:
            self.next_to_act = None

        self.ensure_dealt(self.street)

    def resolve_showdown(self) -> None:
        log.info("resolve_showdown 开始 | pot=%d | stacks=%s", self.pot_cents, dict(self.stacks))
        a, b = self.players
        if not self.in_hand[a] or not self.in_hand[b]:
            raise UserFacingError("有人已弃牌，不应进入摊牌")

        if any(c is None for c in self.hole[a] + self.hole[b]):
            raise UserFacingError("底牌未发齐，无法摊牌")
        if any(c is None for c in self.board):
            raise UserFacingError("公共牌未发齐，无法摊牌")

        hole_a: list[Card] = [c for c in self.hole[a] if c is not None]
        hole_b: list[Card] = [c for c in self.hole[b] if c is not None]
        board: list[Card] = [c for c in self.board if c is not None]

        rank_a = best_hand_rank_7(hole_a + board)
        rank_b = best_hand_rank_7(hole_b + board)

        total_a = self.contributed_total[a]
        total_b = self.contributed_total[b]

        main = 2 * min(total_a, total_b)
        side = abs(total_a - total_b)
        side_owner = a if total_a > total_b else (b if total_b > total_a else None)

        if rank_a > rank_b:
            self.stacks[a] += main
            main_winner = a
        elif rank_b > rank_a:
            self.stacks[b] += main
            main_winner = b
        else:
            self.stacks[a] += main // 2
            self.stacks[b] += main - main // 2
            main_winner = None

        if side > 0 and side_owner is not None:
            self.stacks[side_owner] += side

        self.pot_cents = 0
        self.hand_over = True
        self.win_reason = "showdown"
        self.winner = main_winner
        self.next_to_act = None
        log.info(
            "resolve_showdown 结束 | winner=%s | rank_a=%s | rank_b=%s | stacks=%s",
            main_winner, rank_a, rank_b, dict(self.stacks),
        )

    def get_public_state(self) -> PublicState:
        return PublicState(
            hand_id=self.hand_id,
            button=self.button,
            street=self.street,
            sb_cents=self.sb_cents,
            bb_cents=self.bb_cents,
            pot_cents=self.pot_cents,
            stacks_cents=dict(self.stacks),
            in_hand=dict(self.in_hand),
            hole={p: list(self.hole[p]) for p in self.players},
            board=list(self.board),
            next_to_act=self.next_to_act,
            action_history=list(self.action_history),
            hand_over=self.hand_over,
            winner=self.winner,
            win_reason=self.win_reason,
        )


def load_dotenv(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        log.debug("load_dotenv: 文件不存在 %s", path)
        return {}
    data: dict[str, str] = {}
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        value = v.strip()
        if k.strip().endswith('_PERSONA') and value.startswith('"'):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                value = value.strip('"').strip("'")
        else:
            value = value.strip('"').strip("'")
        data[k.strip()] = value
    safe = {k: (_mask_key(v) if "KEY" in k.upper() else v) for k, v in data.items()}
    log.debug("load_dotenv: 加载 %d 项配置: %s", len(data), safe)
    return data


def save_dotenv(path: str, data: dict[str, str]) -> None:
    lines = [f"{k}=" + (json.dumps(data[k], ensure_ascii=False) if k.endswith('_PERSONA') else data[k])
             for k in sorted(data.keys())]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
