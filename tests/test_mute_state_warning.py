"""検出開始時に VRChat のミュート状態が未取得なら警告することの確認。

UI 側のメソッドは Tk ルートを作らずに、スタブへ束縛して呼び出す。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from snoreguard.app import SnoreGuardApp


def _stub_app(auto_mute: bool, is_vrchat_muted: bool | None) -> SimpleNamespace:
    return SimpleNamespace(
        auto_mute_var=SimpleNamespace(get=lambda: auto_mute),
        is_vrchat_muted=is_vrchat_muted,
        add_log=MagicMock(),
        status_label_var=MagicMock(),
    )


def test_warns_when_auto_mute_on_and_state_unknown():
    stub = _stub_app(auto_mute=True, is_vrchat_muted=None)
    SnoreGuardApp._warn_if_mute_state_unknown(stub)
    stub.add_log.assert_called_once()
    message, level = stub.add_log.call_args[0]
    assert "ミュート状態が未取得" in message
    assert level == "warning"
    stub.status_label_var.set.assert_called_once()


def test_no_warning_when_state_known():
    stub = _stub_app(auto_mute=True, is_vrchat_muted=False)
    SnoreGuardApp._warn_if_mute_state_unknown(stub)
    stub.add_log.assert_not_called()
    stub.status_label_var.set.assert_not_called()


def test_no_warning_when_auto_mute_disabled():
    stub = _stub_app(auto_mute=False, is_vrchat_muted=None)
    SnoreGuardApp._warn_if_mute_state_unknown(stub)
    stub.add_log.assert_not_called()
