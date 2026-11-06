from dataclasses import dataclass
from fractions import Fraction


FORMATS = {"打到一方输光": "bust", "固定手数": "fixed", "盲注升级": "levels"}


@dataclass(frozen=True)
class MatchRules:
    format: str = "bust"
    hands: int = 50
    level_hands: int = 10
    duplicate: bool = False

    @classmethod
    def from_env(cls, env):
        mode = env.get("MATCH_FORMAT", "bust")
        hands = int(env.get("MATCH_HANDS", "50") or 50)
        interval = int(env.get("BLIND_LEVEL_HANDS", "10") or 10)
        if mode not in FORMATS.values() or not 1 <= hands <= 100000 or not 1 <= interval <= 100000:
            raise ValueError("赛制或手数设置无效")
        return cls(mode, hands, interval, env.get("DUPLICATE_MATCH", "false").lower() == "true")

    def level(self, hand):
        return (max(1, hand) - 1) // self.level_hands if self.format == "levels" else 0

    def blinds(self, sb, bb, hand):
        multiplier = Fraction(3, 2) ** self.level(hand)
        return max(1, round(sb * multiplier)), max(1, round(bb * multiplier))

    def ended(self, state):
        return state.hand_over and (min(state.stacks.values()) <= 0 or
                                   (self.format == "fixed" and state.hand_id >= self.hands))


class MatchLedger:
    def __init__(self):
        self.hands = 0
        self.biggest_pot = 0
        self.seen = set()
        self.vpip = {p: set() for p in ("AI_A", "AI_B")}
        self.pfr = {p: set() for p in ("AI_A", "AI_B")}
        self.showdowns = dict.fromkeys(("AI_A", "AI_B"), 0)
        self.showdown_wins = dict.fromkeys(("AI_A", "AI_B"), 0)
        self.times = {p: [] for p in ("AI_A", "AI_B")}

    def action(self, state, player, action):
        if state.street == "preflop":
            if action in ("call", "bet", "raise"):
                self.vpip[player].add(state.hand_id)
            if action in ("bet", "raise"):
                self.pfr[player].add(state.hand_id)

    def finish_hand(self, state):
        if not state.hand_over or state.hand_id in self.seen:
            return False
        self.seen.add(state.hand_id)
        self.hands += 1
        self.biggest_pot = max(self.biggest_pot, sum(state.contributed_total.values()))
        if state.win_reason == "showdown":
            for p in state.players:
                self.showdowns[p] += 1
                self.showdown_wins[p] += p == state.winner
        return True

    def stats(self, model_stats):
        return {p: dict(vpip=len(self.vpip[p]) / max(1, self.hands),
                        pfr=len(self.pfr[p]) / max(1, self.hands),
                        showdown_win=self.showdown_wins[p] / max(1, self.showdowns[p]),
                        showdown_count=self.showdowns[p],
                        thinking_seconds=sum(self.times[p]) / max(1, len(self.times[p])),
                        thinking_count=len(self.times[p]),
                        invalid_outputs=model_stats[p]["invalid_outputs"],
                        fallbacks=model_stats[p]["fallbacks"])
                for p in ("AI_A", "AI_B")}


def combine_stats(first, second, first_hands, second_hands):
    result = {}
    for player, current in second.items():
        previous = first[player]
        stats = dict(current)
        for key in ("vpip", "pfr"):
            stats[key] = (previous[key] * first_hands + current[key] * second_hands) / max(1, first_hands + second_hands)
        for value, count in (("showdown_win", "showdown_count"), ("thinking_seconds", "thinking_count")):
            stats[count] = previous[count] + current[count]
            stats[value] = (previous[value] * previous[count] + current[value] * current[count]) / max(1, stats[count])
        for key in ("invalid_outputs", "fallbacks"):
            stats[key] = previous[key] + current[key]
        result[player] = stats
    return result
