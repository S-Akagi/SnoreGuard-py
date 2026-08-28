from snoreguard.mute_policy import MuteAction, decide_mute_action


def test_unmuted_sends_toggle():
    assert decide_mute_action(False) is MuteAction.SEND_TOGGLE


def test_muted_does_nothing():
    assert decide_mute_action(True) is MuteAction.ALREADY_MUTED


def test_unknown_state_never_toggles_blindly():
    assert decide_mute_action(None) is MuteAction.UNKNOWN_SKIP
