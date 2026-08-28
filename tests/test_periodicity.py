from datetime import datetime, timedelta

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings, SnoreEvent

T0 = datetime(2026, 1, 1, 0, 0, 0)


def _proc(**kw):
    hits = []
    settings = RuleSettings(
        periodicity_event_count=4,
        periodicity_window_seconds=45,
        min_event_interval_seconds=2.0,
        max_event_interval_seconds=10.0,
        **kw,
    )
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


def test_events_outside_window_are_dropped():
    proc, hits = _proc()
    proc.register_event(_ev(0))
    proc.register_event(_ev(5))
    proc.register_event(_ev(60))  # max_interval を超えるのでリセットされる
    assert len(proc.recent_events) == 1
