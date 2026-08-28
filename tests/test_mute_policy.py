"""ミュート判断ポリシーと、その呼び出し側の配線（盲目トグル禁止）。

UI 側のメソッドは Tk ルートを作らずに、スタブへ束縛して呼び出す。
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from snoreguard import single_instance
from snoreguard.app import SnoreGuardApp
from snoreguard.mute_policy import MuteAction, decide_mute_action


def test_unmuted_sends_toggle():
    assert decide_mute_action(False) is MuteAction.SEND_TOGGLE


def test_muted_does_nothing():
    assert decide_mute_action(True) is MuteAction.ALREADY_MUTED


def test_unknown_state_never_toggles_blindly():
    assert decide_mute_action(None) is MuteAction.UNKNOWN_SKIP


def _stub_app(is_vrchat_muted: bool | None) -> SimpleNamespace:
    """_trigger_vrchat_mute に必要な最小の依存だけを持つスタブ"""
    return SimpleNamespace(
        is_vrchat_muted=is_vrchat_muted,
        vrc_handler=MagicMock(),
        add_log=MagicMock(),
        muted_by_snoreguard=False,
    )


def test_trigger_does_not_toggle_when_state_unknown():
    stub = _stub_app(None)
    SnoreGuardApp._trigger_vrchat_mute(stub)
    stub.vrc_handler.toggle_mute.assert_not_called()
    assert stub.muted_by_snoreguard is False


def test_trigger_toggles_once_when_unmuted():
    stub = _stub_app(False)
    SnoreGuardApp._trigger_vrchat_mute(stub)
    stub.vrc_handler.toggle_mute.assert_called_once_with()
    assert stub.muted_by_snoreguard is True


def test_trigger_does_not_toggle_when_already_muted():
    stub = _stub_app(True)
    SnoreGuardApp._trigger_vrchat_mute(stub)
    stub.vrc_handler.toggle_mute.assert_not_called()


@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="Windows では実際にミューテックスを取得する"
)
def test_acquire_returns_true_on_non_windows():
    assert single_instance.acquire() is True
