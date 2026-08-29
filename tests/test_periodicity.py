from datetime import datetime, timedelta

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings, SnoreEvent

T0 = datetime(2026, 1, 1, 0, 0, 0)


def _proc(**kw):
    hits = []
    params = {
        "periodicity_event_count": 4,
        "periodicity_window_seconds": 45,
        "min_event_interval_seconds": 2.0,
        "max_event_interval_seconds": 10.0,
    }
    params.update(kw)
    settings = RuleSettings(**params)
    proc = RuleBasedProcessor(settings, lambda: hits.append(1), clock=lambda: T0)
    return proc, hits


def _ev(sec):
    return SnoreEvent(timestamp=T0 + timedelta(seconds=sec), duration=0.5)


def test_four_regular_snores_fire_once():
    proc, hits = _proc()
    for t in (0, 4, 8, 12):
        proc.register_event(_ev(t))
    assert hits == [1]
    assert len(proc.recent_events) == 0  # 発火後はクリア


def test_bursts_within_min_interval_count_as_one():
    proc, hits = _proc()
    for t in (0, 0.3, 0.6, 0.9):  # 1 秒内の 4 バースト
        proc.register_event(_ev(t))
    assert hits == []
    assert len(proc.recent_events) == 1


def test_gap_longer_than_max_interval_resets_sequence():
    proc, hits = _proc()
    for t in (0, 4, 8):
        proc.register_event(_ev(t))
    proc.register_event(_ev(30))  # 22 秒空いた → 周期列リセット
    assert hits == []
    assert len(proc.recent_events) == 1


def test_event_after_long_gap_resets_before_window_trim():
    """max_interval 超過のリセットが先に効くので、ウィンドウのトリムには到達しない"""
    proc, hits = _proc()
    proc.register_event(_ev(0))
    proc.register_event(_ev(5))
    proc.register_event(_ev(60))  # max_interval を超えるのでリセットされる
    assert len(proc.recent_events) == 1


def test_events_outside_window_are_dropped():
    """max_interval 内で並ぶイベントでも、周期ウィンドウから外れたものは捨てる"""
    # 発火しない大きめの event_count と短いウィンドウで、トリムだけを観察する
    proc, hits = _proc(periodicity_event_count=10, periodicity_window_seconds=15)
    for t in (0, 8, 16, 24):  # 間隔 8s は max_event_interval(10s) 以内
        proc.register_event(_ev(t))
    assert hits == []
    # 最後のイベント(24s)から 15 秒より前の 0s・8s は落ちている
    assert [(e.timestamp - T0).total_seconds() for e in proc.recent_events] == [16, 24]


def test_injected_clock_is_used_for_chunk_timestamps():
    """chunk_start 省略時のイベント時刻は wall clock ではなく注入した clock から決まる"""
    import numpy as np

    sr = 16000
    proc, _hits = _proc()
    # チャンク内 0.2s〜0.8s だけ鳴らす（チャンク末尾で閉じるので必ずイベント化する）
    audio = np.zeros(sr, dtype=np.float32)
    t = np.arange(int(0.6 * sr)) / sr
    tone = np.zeros_like(t)
    for k in range(1, 9):
        tone += np.sin(2 * np.pi * 100.0 * k * t) / (k * k)
    audio[int(0.2 * sr) : int(0.8 * sr)] = (tone / np.max(np.abs(tone)) * 0.3).astype(
        np.float32
    )

    result = proc.process_audio_chunk(audio)
    # chunk_start は clock() の 1 チャンク分（1 秒）前。音は その 0.2 秒後から。
    expected = T0 - timedelta(seconds=1.0) + timedelta(seconds=0.2)
    actual = result["first_event_timestamp"]
    assert actual is not None
    assert abs((actual - expected).total_seconds()) < 0.1
