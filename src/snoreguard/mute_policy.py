"""VRChat ミュート操作の判断。

/input/Voice はトグルなので、現在のミュート状態が分からないまま送ると
「ミュート解除」になり得る。状態が既知のときだけ送る。
"""

from enum import Enum


class MuteAction(Enum):
    SEND_TOGGLE = "send_toggle"  # 未ミュート → トグルを送る
    ALREADY_MUTED = "already_muted"  # 既にミュート → 何もしない
    UNKNOWN_SKIP = "unknown_skip"  # 状態不明 → 送らない（盲目トグル禁止）


def decide_mute_action(is_muted: bool | None) -> MuteAction:
    if is_muted is None:
        return MuteAction.UNKNOWN_SKIP
    return MuteAction.ALREADY_MUTED if is_muted else MuteAction.SEND_TOGGLE
