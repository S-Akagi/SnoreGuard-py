from datetime import datetime, timedelta

import numpy as np

from core.rule_processor import RuleBasedProcessor, SegmentProcessor
from core.settings import RuleSettings

SR, HOP = 16000, 200
FRAME_DT = HOP / SR  # 0.0125 s
T0 = datetime(2026, 1, 1, 0, 0, 0)


def _feats(n):
    return {
        "rms": np.full(n, 0.05, dtype=np.float32),
        "f0": np.full(n, 100.0, dtype=np.float32),
    }


def _mask(n, true_ranges):
    m = np.zeros(n, dtype=bool)
    for a, b in true_ranges:
        m[a:b] = True
    return m


def test_segment_inside_one_chunk():
    sp = SegmentProcessor(
        HOP, SR, RuleSettings(min_duration_seconds=0.2, max_duration_seconds=3.0)
    )
    events = sp.process_segments(_mask(81, [(10, 40)]), _feats(81), T0)
    assert len(events) == 1
    assert abs(events[0].duration - 30 * FRAME_DT) < 1e-9
    assert events[0].timestamp == T0 + timedelta(seconds=10 * FRAME_DT)


def test_segment_spanning_two_chunks_is_one_event():
    sp = SegmentProcessor(HOP, SR, RuleSettings())
    first = sp.process_segments(_mask(81, [(60, 81)]), _feats(81), T0)
    assert first == []  # チャンク末尾まで True → 持ち越し
    second = sp.process_segments(
        _mask(81, [(0, 20)]), _feats(81), T0 + timedelta(seconds=1)
    )
    assert len(second) == 1
    assert abs(second[0].duration - (21 + 20) * FRAME_DT) < 1e-9
    assert second[0].timestamp == T0 + timedelta(seconds=60 * FRAME_DT)


def test_long_continuous_sound_is_rejected_by_max_duration():
    sp = SegmentProcessor(HOP, SR, RuleSettings(max_duration_seconds=3.0))
    all_true = _mask(81, [(0, 81)])
    for i in range(4):  # 4 秒連続
        assert (
            sp.process_segments(all_true, _feats(81), T0 + timedelta(seconds=i)) == []
        )
    closing = sp.process_segments(
        _mask(81, [(0, 5)]), _feats(81), T0 + timedelta(seconds=4)
    )
    assert closing == []  # 合計 > 3 秒なので棄却


def test_too_short_segment_is_rejected():
    sp = SegmentProcessor(HOP, SR, RuleSettings(min_duration_seconds=0.2))
    assert sp.process_segments(_mask(81, [(0, 5)]), _feats(81), T0) == []


def test_reset_drops_open_segment():
    sp = SegmentProcessor(HOP, SR, RuleSettings())
    sp.process_segments(_mask(81, [(60, 81)]), _feats(81), T0)
    sp.reset()
    assert (
        sp.process_segments(_mask(81, [(0, 5)]), _feats(81), T0 + timedelta(seconds=1))
        == []
    )


def test_skipped_chunk_drops_open_segment(monkeypatch):
    """特徴量抽出に失敗して 1 チャンク分の音声が欠落したら持ち越しを捨てる"""
    import core.rule_processor as rp

    processor = RuleBasedProcessor(RuleSettings(), lambda: None)
    processor.segment_processor.process_segments(_mask(81, [(0, 81)]), _feats(81), T0)
    assert processor.segment_processor._open_frames == 81

    def boom(*args, **kwargs):
        raise ValueError("pyin failed")

    monkeypatch.setattr(rp.librosa, "pyin", boom)
    assert processor.process_audio_chunk(np.zeros(16000, dtype=np.float32)) == {}
    assert processor.segment_processor._open_frames == 0
