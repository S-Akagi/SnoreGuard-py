"""無音ウォッチドッグが UI タイマー駆動で、解析結果の途絶も検知することの確認。

UI 側のメソッドは Tk ルートを作らずに、スタブへ束縛して呼び出す。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from snoreguard.app import SnoreGuardApp

TIMEOUT_S = SnoreGuardApp.SILENCE_WARN_AFTER_S


def _stub_app(sound_ago: float, analysis_ago: float, warned: bool = False):
    now = datetime.now()
    return SimpleNamespace(
        SILENCE_WARN_AFTER_S=TIMEOUT_S,
        _last_sound_time=now - timedelta(seconds=sound_ago),
        _last_analysis_time=now - timedelta(seconds=analysis_ago),
        _silence_warned=warned,
        add_log=MagicMock(),
        status_label_var=MagicMock(),
    )


def _messages(stub) -> list[str]:
    return [call.args[0] for call in stub.add_log.call_args_list]


def test_silent_microphone_warns_once():
    """解析結果は届いているが音が無い → 無音警告を 1 回だけ出す"""
    stub = _stub_app(sound_ago=TIMEOUT_S + 5, analysis_ago=0)
    SnoreGuardApp._check_silence(stub)
    assert stub._silence_warned is True
    assert len(_messages(stub)) == 1
    assert "無音" in _messages(stub)[0]

    SnoreGuardApp._check_silence(stub)  # 2 回目は何も出さない
    assert len(_messages(stub)) == 1


def test_recovery_logs_once():
    """音が戻ったら復帰ログを出して警告フラグを下ろす"""
    stub = _stub_app(sound_ago=0, analysis_ago=0, warned=True)
    SnoreGuardApp._check_silence(stub)
    assert stub._silence_warned is False
    assert _messages(stub) == ["音声入力を再び検知しました。"]


def test_no_analysis_at_all_warns():
    """解析結果自体が届かない（ワーカー停止）→ 別メッセージで警告する"""
    stub = _stub_app(sound_ago=0, analysis_ago=TIMEOUT_S + 5)
    SnoreGuardApp._check_silence(stub)
    assert stub._silence_warned is True
    assert "解析結果が届いていません" in _messages(stub)[0]


def test_within_timeout_does_not_warn():
    stub = _stub_app(sound_ago=TIMEOUT_S - 5, analysis_ago=TIMEOUT_S - 5)
    SnoreGuardApp._check_silence(stub)
    assert stub._silence_warned is False
    assert _messages(stub) == []


def test_note_analysis_result_updates_timestamps():
    """_note_analysis_result は時刻を記録するだけで警告判断はしない"""
    stub = SimpleNamespace(
        _last_sound_time=None, _last_analysis_time=None, add_log=MagicMock()
    )
    SnoreGuardApp._note_analysis_result(
        stub, {"analysis_results": {"rms": np.full(4, 0.1, dtype=np.float32)}}
    )
    assert stub._last_analysis_time is not None
    assert stub._last_sound_time is not None
    stub.add_log.assert_not_called()


def test_note_analysis_result_ignores_silent_rms():
    """無音の解析結果でも到着時刻だけは更新する"""
    stub = SimpleNamespace(
        _last_sound_time=None, _last_analysis_time=None, add_log=MagicMock()
    )
    SnoreGuardApp._note_analysis_result(
        stub, {"analysis_results": {"rms": np.zeros(4, dtype=np.float32)}}
    )
    assert stub._last_analysis_time is not None
    assert stub._last_sound_time is None
