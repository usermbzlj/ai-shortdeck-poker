import core


PLAYERS = ("AI_A", "AI_B")
TAG_LABELS = {"big_pot": "大底池", "bluff": "诈唬成功", "bad_beat": "爆冷 / Bad Beat", "hero_call": "英雄跟注"}


def category(hand, player):
    hole = [core.parse_card(c) for c in hand.get("hole", {}).get(player, []) if c]
    board = [core.parse_card(c) for c in hand.get("board", []) if c]
    count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[hand.get("street", "preflop")]
    cards = hole + board[:count]
    if len(hole) != 2:
        return None
    if len(cards) < 5:
        return int(hole[0][0] == hole[1][0])
    return core.best_hand_rank_7(cards)[0]


def tags_for_hand(hand):
    tags = []
    if hand.get("pot_cents", 0) >= 20 * max(1, hand.get("blinds", {}).get("bb", 100)):
        tags.append("big_pot")
    winner = hand.get("winner")
    actions = hand.get("actions", [])
    if winner:
        rank = category(hand, winner)
        if hand.get("reason") == "fold" and len(actions) >= 2:
            bet = actions[-2]
            if bet["player"] == winner and bet["action"] in ("bet", "raise") and bet["street"] != "preflop":
                at_bet = dict(hand, street=bet["street"], board=bet.get("board", hand.get("board", [])),
                              hole=bet.get("hole", hand.get("hole", {})))
                if category(at_bet, winner) == 0:
                    tags.append("bluff")
        if hand.get("reason") == "showdown" and rank is not None and rank <= 1 and any(
                a["player"] == winner and a["street"] == "river" and a["action"] == "call" and a.get("paid_cents", 0) > 0 for a in actions):
            tags.append("hero_call")
        equity = (hand.get("all_in") or {}).get("equity")
        if equity and hand.get("reason") == "showdown" and any(
                p != winner and equity[p] + equity.get("tie", 0) / 2 >= .70 for p in PLAYERS):
            tags.append("bad_beat")
    return tags


def net_results(hand):
    return {p: hand["final_stacks"][p] - hand["start_stacks"][p] for p in PLAYERS}


def adjusted_net(hand):
    actual = net_results(hand)
    all_in = hand.get("all_in") or {}
    if not all_in.get("equity") or hand.get("reason") != "showdown":
        return actual
    equity, pot = all_in["equity"], all_in["pot_cents"]
    return {p: actual[p] + round(pot * (equity[p] + equity.get("tie", 0) / 2)) -
            (pot if hand["winner"] == p else pot // 2 if hand["winner"] is None else 0)
            for p in PLAYERS}


def aggregate(hands):
    stats = {p: dict(hands=0, vpip_count=0, pfr_count=0, threebet_count=0, threebet_opps=0,
                     bets=0, calls=0, saw_flop=0, showdown_count=0, showdown_wins=0,
                     think_total=0., think_count=0, invalid_outputs=0, decisions=0, retries=0, fallbacks=0,
                     net_cents=0, ev_cents=0, ev_pending=0) for p in PLAYERS}
    for hand in hands:
        actions = hand.get("actions", [])
        raises, raiser, opportunities = 0, None, set()
        threebets = set()
        for action in actions:
            if action["street"] != "preflop":
                continue
            p, act = action["player"], action["action"]
            if raises == 1 and p != raiser and "raise" in action.get("legal_actions", []) and p not in opportunities:
                opportunities.add(p)
                if act == "raise":
                    threebets.add(p)
            if act in ("bet", "raise"):
                raises += 1
                raiser = p
        net, ev = net_results(hand), adjusted_net(hand)
        for p, s in stats.items():
            mine = [a for a in actions if a["player"] == p]
            pre = [a for a in mine if a["street"] == "preflop"]
            post = [a for a in mine if a["street"] != "preflop"]
            s["hands"] += 1
            s["vpip_count"] += any(a["action"] in ("call", "bet", "raise") for a in pre)
            s["pfr_count"] += any(a["action"] in ("bet", "raise") for a in pre)
            s["threebet_opps"] += p in opportunities
            s["threebet_count"] += p in threebets
            s["bets"] += sum(a["action"] in ("bet", "raise") for a in post)
            s["calls"] += sum(a["action"] == "call" for a in post)
            s["saw_flop"] += p in hand.get("saw_flop", [])
            s["showdown_count"] += hand.get("reason") == "showdown"
            s["showdown_wins"] += hand.get("reason") == "showdown" and hand.get("winner") == p
            for decision in hand.get("decisions", []):
                if decision["player"] == p and decision.get("think_seconds") is not None:
                    s["think_total"] += decision["think_seconds"]
                    s["think_count"] += 1
            counters = hand.get("model_stats", {}).get(p, {})
            for key in ("invalid_outputs", "decisions", "retries", "fallbacks"):
                s[key] += counters.get(key, 0)
            s["net_cents"] += net[p]
            s["ev_cents"] += ev[p]
            s["ev_pending"] += bool(hand.get("all_in") and not hand["all_in"].get("equity"))
    for s in stats.values():
        s["outputs"] = s["decisions"] + s["retries"]
        for key, num, den in (("vpip", "vpip_count", "hands"), ("pfr", "pfr_count", "hands"),
                              ("threebet", "threebet_count", "threebet_opps"), ("wtsd", "showdown_count", "saw_flop"),
                              ("wsd", "showdown_wins", "showdown_count"), ("invalid_rate", "invalid_outputs", "outputs")):
            s[key] = s[num] / s[den] if s[den] else None
        s["af"] = s["bets"] / s["calls"] if s["calls"] else float("inf") if s["bets"] else None
        s["think_seconds"] = s["think_total"] / s["think_count"] if s["think_count"] else None
        s["luck_cents"] = s["net_cents"] - s["ev_cents"]
    return stats


def curve_points(hands):
    ordered = sorted(hands, key=lambda h: h["hand_no"])
    if not ordered:
        return []
    return [dict(hand_no=0, stacks=ordered[0]["start_stacks"], record=None)] + [
        dict(hand_no=h["hand_no"], stacks=h["final_stacks"], record=h) for h in ordered]
