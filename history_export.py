import json

from history_store import without_secrets
import core


def pokerstars(hand):
    names = {p: " ".join(n.splitlines()) for p, n in hand["names"].items()}
    seats = hand["seats"]
    sb, bb = hand["blinds"]["sb"], hand["blinds"]["bb"]
    button = hand["button"]
    opponent = next(p for p in seats if p != button)
    lines = [f'PokerStars Hand #{hand["match_id"][:8]}-{hand["hand_no"]}: Short Deck Hold\'em No Limit ({core.format_money(sb)}/{core.format_money(bb)} USD)',
             f'Table \'Short Deck Arena\' 2-max Seat #{seats.index(button) + 1} is the button']
    lines += [f'Seat {i + 1}: {names[p]} ({core.format_money(hand["start_stacks"][p])} in chips)' for i, p in enumerate(seats)]
    lines += [f'{names[button]}: posts small blind {core.format_money(min(sb, hand["start_stacks"][button]))}',
              f'{names[opponent]}: posts big blind {core.format_money(min(bb, hand["start_stacks"][opponent]))}', "*** HOLE CARDS ***"]
    for p in seats:
        if all(hand["hole"][p]):
            lines.append(f'Dealt to {names[p]} [{" ".join(hand["hole"][p])}]')
    street = "preflop"
    contributed = {button: min(sb, hand["start_stacks"][button]), opponent: min(bb, hand["start_stacks"][opponent])}
    current_bet = max(contributed.values())
    for action in hand["actions"]:
        if action["street"] != street:
            street = action["street"]
            board = hand["board"]
            if street == "flop":
                lines.append(f'*** FLOP *** [{" ".join(board[:3])}]')
            else:
                count = 3 if street == "turn" else 4
                lines.append(f'*** {street.upper()} *** [{" ".join(board[:count])}] [{board[count]}]')
            contributed = dict.fromkeys(seats, 0)
            current_bet = 0
        p, act, paid = action["player"], action["action"], action["paid_cents"]
        if act in ("check", "fold"):
            text = "checks" if act == "check" else "folds"
        elif act == "call":
            text = "calls " + core.format_money(paid)
        elif act == "bet":
            text = "bets " + core.format_money(paid)
        else:
            target = contributed[p] + paid
            text = f'raises {core.format_money(target - current_bet)} to {core.format_money(target)}'
        contributed[p] += paid
        current_bet = max(current_bet, contributed[p])
        lines.append(f'{names[p]}: {text}' + (" and is all-in" if action.get("all_in") and act != "fold" else ""))
    if hand["reason"] == "showdown":
        for count, label in ((3, "FLOP"), (4, "TURN"), (5, "RIVER")):
            if {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street] < count:
                board = hand["board"]
                lines.append(f'*** {label} *** [{" ".join(board[:count])}]')
        lines.append("*** SHOW DOWN ***")
        for p in seats:
            lines.append(f'{names[p]}: shows [{" ".join(hand["hole"][p])}]')
    if hand["winner"]:
        lines.append(f'{names[hand["winner"]]} collected {core.format_money(hand["pot_cents"])} from pot')
    else:
        lines.append("Pot split between players")
    lines += ["*** SUMMARY ***", f'Total pot {core.format_money(hand["pot_cents"])} | Rake $0.00',
              f'Board [{" ".join(c for c in hand["board"] if c)}]', "Short deck: 36 cards, flush beats full house, A6789 is a straight."]
    return "\n".join(lines) + "\n"


def export_text(hands):
    return "\n".join(pokerstars(h) for h in sorted(hands, key=lambda h: (h["match_id"], h["hand_no"])))


def export_json(hands):
    return json.dumps(dict(version=1, game="short_deck", hands=without_secrets(hands)), ensure_ascii=False, indent=2)
