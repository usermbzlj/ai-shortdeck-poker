from copy import deepcopy

import core
from analytics import PLAYERS, tags_for_hand


def snapshot(state, names, models, label, analysis=None, speech=None, decision=None):
    return dict(label=label, hand_no=state.hand_id, button=state.button, street=state.street,
                pot_cents=state.pot_cents, stacks=dict(state.stacks),
                hole={p: [core.card_to_text(c) if c else "" for c in state.hole[p]] for p in PLAYERS},
                board=[core.card_to_text(c) if c else "" for c in state.board],
                next_to_act=state.next_to_act, in_hand=dict(state.in_hand),
                contributed=dict(state.contributed_street), hand_over=state.hand_over,
                winner=state.winner, reason=state.win_reason, names=dict(names), models=dict(models),
                swapped=state.replay_swapped, analysis=dict(analysis or {}), speech=dict(speech or {}),
                decision=deepcopy(decision))


class HandTrace:
    def __init__(self, match_id, state, names, models, model_stats):
        self.names, self.models = names, models
        self.stats_start = deepcopy(model_stats)
        self.before = None
        self.record = dict(match_id=match_id, hand_no=state.hand_id, names=dict(names), models=dict(models),
                           button=state.button, seats=list(state._seat_order()),
                           blinds=dict(sb=state.sb_cents, bb=state.bb_cents),
                           start_stacks={p: state.stacks[p] + state.contributed_total[p] for p in PLAYERS},
                           actions=[], decisions=[], commentary=[], frames=[], all_in=None, saw_flop=[])
        self.frame(state, "盲注已下 · 等待发牌")

    def frame(self, state, label, analysis=None, speech=None, decision=None):
        frame = snapshot(state, self.names, self.models, label, analysis, speech, decision)
        if state.street != "preflop":
            for p in PLAYERS:
                if state.in_hand[p] and p not in self.record["saw_flop"]:
                    self.record["saw_flop"].append(p)
        self.record["frames"].append(frame)
        return frame

    def before_action(self, state, player, decision=None, analysis=None, speech=None):
        self.before = self.frame(state, self.names[player] + " · 决策", analysis, speech, decision)
        self.before["legal_actions"] = list(state.legal_actions(player)["actions"])

    def after_action(self, state, player, action, target, analysis=None, speech=None):
        before = self.before
        if before is None:
            raise ValueError("缺少行动前快照")
        paid = max(0, before["stacks"][player] - state.stacks[player])
        decision = before.get("decision")
        entry = dict(player=player, street=before["street"], action=action, paid_cents=paid,
                     to_cents=target, legal_actions=before["legal_actions"], pot_before=before["pot_cents"],
                     all_in=state.stacks[player] == 0, decision=deepcopy(decision))
        self.record["actions"].append(entry)
        if decision is not None:
            self.record["decisions"].append(dict(decision, player=player))
        label = {"fold": "弃牌", "check": "过牌", "call": "跟注", "bet": "下注", "raise": "加注"}[action]
        self.frame(state, self.names[player] + " " + label + (" " + core.format_money(paid) if paid else ""),
                   analysis, speech, decision)
        self.before = None

    def detect_all_in(self, state):
        if self.record["all_in"] is None and not state.hand_over and state.next_to_act is None and min(state.stacks.values()) == 0:
            count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[state.street]
            self.record["all_in"] = dict(street=state.street, board=[core.card_to_text(c) for c in state.board[:count] if c],
                                         pot_cents=2 * min(state.contributed_total.values()), hole=None, equity=None)
        all_in = self.record["all_in"]
        if all_in and all_in["hole"] is None and all(all(state.hole[p]) for p in PLAYERS):
            all_in["hole"] = {p: [core.card_to_text(c) for c in state.hole[p]] for p in PLAYERS}
            return deepcopy(all_in)
        return None

    def finish(self, state, model_stats, analysis=None, speech=None):
        self.frame(state, "本手结算", analysis, speech)
        self.record.update(street=state.street, hole={p: [core.card_to_text(c) if c else "" for c in state.hole[p]] for p in PLAYERS},
                           board=[core.card_to_text(c) if c else "" for c in state.board],
                           final_stacks=dict(state.stacks), winner=state.winner, reason=state.win_reason,
                           pot_cents=sum(state.contributed_total.values()),
                           model_stats={p: {k: max(0, v - self.stats_start[p].get(k, 0)) for k, v in model_stats[p].items()} for p in PLAYERS})
        self.record["tags"] = tags_for_hand(self.record)
        return deepcopy(self.record)
