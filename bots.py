import random

import core


STYLES = ("紧凶", "松凶", "跟注站")
BASE_URL = "builtin://bot"


def reflection(style, result):
    return {
        "紧凶": {"赢": "纪律与价值下注兑现了优势，下一场继续耐心等好机会。",
                 "输": "这次结果不理想，先复盘关键底池，纪律不能丢。", "平": "势均力敌，下一场我会更精细地选择进攻时机。"},
        "松凶": {"赢": "敢施压才有机会！这场节奏由我掌控，继续开火。",
                 "输": "这局火力有点过猛，不过我可不会就此收手！", "平": "还没分出胜负？下一场我会让底池更热闹。"},
        "跟注站": {"赢": "跟到底也能见到彩虹，好在关键时候没有放弃。",
                  "输": "看来有些牌确实该放下，下次少付一点学费。", "平": "一路跟下来竟然打平，再看几张牌也无妨。"},
    }.get(style, {}).get(result, "把关键手牌带回复盘，下场再见。")


def configured(profile):
    return profile.base_url == BASE_URL and profile.model in STYLES


def decide(state, player, style="紧凶", rng=None):
    rng = rng or random.Random()
    legal = state.legal_actions(player)
    actions = legal["actions"]
    if not actions or state.next_to_act != player:
        raise ValueError("机器人当前无需行动")
    hole = [c for c in state.hole[player] if c]
    if len(hole) != 2:
        raise ValueError("机器人需要完整底牌")
    ranks = [c[0] for c in hole]
    strength = sum(ranks) / 32 + (.25 if ranks[0] == ranks[1] else 0)
    strength += .12 if hole[0][1] == hole[1][1] else 0
    board = [c for c in state.board if c]
    if len(board) >= 3:
        rank = core.best_hand_rank_7(hole + board)
        strength = .25 + rank[0] * .13
    aggression = {"紧凶": .35, "松凶": .62, "跟注站": .10}.get(style, .35)
    passive = "check" if "check" in actions else "call" if "call" in actions else "fold"
    action, target = passive, None
    sizing = "raise" if "raise" in actions else "bet" if "bet" in actions else None
    if sizing and rng.random() < aggression * min(1.4, strength):
        action = sizing
        minimum = legal["min_raise_to_cents" if sizing == "raise" else "min_bet_to_cents"]
        maximum = legal["max_to_cents"]
        target = min(maximum, max(minimum or state.bb_cents,
                                 state.contributed_street[player] + state.to_call_cents(player) +
                                 round((state.pot_cents + state.to_call_cents(player)) * .5)))
    elif passive == "call" and style != "跟注站":
        price = state.to_call_cents(player) / max(1, state.pot_cents + state.to_call_cents(player))
        if strength < .60 and rng.random() < price + (.12 if style == "紧凶" else 0):
            action = "fold"
    speech = rng.choice(("别急，河牌才见真章。", "这点筹码，还吓不到我。", "有好牌，也要有好故事。")) if rng.random() < .4 else ""
    analysis = {"fold": "赔率不够理想，保存筹码等待更好的机会。",
                "check": "先控制底池，观察对手下一步的反应。",
                "call": "牌力与底池赔率允许继续，看看接下来会发生什么。",
                "bet": "用半池尺度主动施压，同时保护自己的范围。",
                "raise": "通过加注争取主动权，不让对手轻松实现胜率。"}[action]
    return dict(action=action, to_cents=target, analysis=analysis, trash_talk=speech)
