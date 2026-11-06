import core


PROVIDER = "真人（我来打）"
BASE_URL = "builtin://human"


def configured(profile):
    return profile.base_url == BASE_URL


def validate_env(env):
    seats = [p for p in ("A", "B") if env.get(p + "_PROVIDER") == PROVIDER or env.get(p + "_BASE_URL") == BASE_URL]
    if len(seats) > 1:
        raise core.UserFacingError("目前只支持一个真人座位，请将另一位选手设为 AI 或内置机器人。")


def validate_action(state, player, action, target):
    legal = state.legal_actions(player)
    if action not in legal["actions"]:
        raise core.UserFacingError("当前不能执行这个动作，请使用操作栏中的合法动作。")
    if action in ("bet", "raise"):
        maximum = legal["max_to_cents"]
        minimum = min(legal["min_bet_to_cents" if action == "bet" else "min_raise_to_cents"] or maximum, maximum)
        if type(target) is not int or not minimum <= target <= maximum:
            raise core.UserFacingError(f"下注目标必须在 {core.format_money(minimum)} 至 {core.format_money(maximum)} 之间。")
