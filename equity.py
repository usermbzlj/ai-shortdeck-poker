from functools import lru_cache
from itertools import combinations
import random

import core


def card_key(hole_a, hole_b, board):
    return tuple(sorted(hole_a)), tuple(sorted(hole_b)), tuple(sorted(board))


@lru_cache(maxsize=256)
def calculate_equity(hole_a: tuple[str, ...], hole_b: tuple[str, ...],
                     board: tuple[str, ...], samples: int = 2000) -> tuple[float, float, float]:
    """返回 A 胜 / B 胜 / 平局概率；翻牌后精确枚举，翻牌前固定种子抽样。"""
    if len(hole_a) != 2 or len(hole_b) != 2 or len(board) not in (0, 3, 4, 5):
        raise ValueError("胜率计算需要双方完整底牌及合法公共牌张数")
    texts = hole_a + hole_b + board
    cards = [core.parse_card(c) for c in texts]
    if len(set(cards)) != len(cards):
        raise ValueError("胜率计算中存在重复牌")
    if samples <= 0:
        raise ValueError("抽样次数必须为正")
    a, b, known_board = cards[:2], cards[2:4], cards[4:]
    remaining = [c for c in core.build_short_deck() if c not in cards]
    need = 5 - len(board)
    rng = random.Random(repr((hole_a, hole_b, board)))
    runouts = (rng.sample(remaining, need) for _ in range(samples)) if not board else combinations(remaining, need)
    wins_a = wins_b = ties = 0
    for runout in runouts:
        full = known_board + list(runout)
        rank_a = core.best_hand_rank_7(a + full)
        rank_b = core.best_hand_rank_7(b + full)
        wins_a += rank_a > rank_b
        wins_b += rank_b > rank_a
        ties += rank_a == rank_b
    count = wins_a + wins_b + ties
    return wins_a / count, wins_b / count, ties / count
