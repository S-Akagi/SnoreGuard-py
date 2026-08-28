import numpy as np

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings


def _tone(freq, sr=16000, sec=1.0, amp=0.3):
    t = np.arange(int(sr * sec)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_high_pitch_is_measured_outside_snore_range():
    proc = RuleBasedProcessor(RuleSettings(f0_min_hz=70, f0_max_hz=150), lambda: None)
    proc.process_audio_chunk(_tone(440))  # フィルタ状態を温める
    res = proc.process_audio_chunk(_tone(440))
    f0 = res["analysis_results"]["f0"]
    voiced = f0[f0 > 0]
    assert len(voiced) > 0
    assert np.median(voiced) > 300  # 旧実装では 146Hz に折り返していた
    assert not res["pass_masks"]["f0_range"].any()


def test_low_pitch_is_inside_range():
    proc = RuleBasedProcessor(RuleSettings(f0_min_hz=70, f0_max_hz=150), lambda: None)
    proc.process_audio_chunk(_tone(100))
    res = proc.process_audio_chunk(_tone(100))
    f0 = res["analysis_results"]["f0"]
    voiced = f0[f0 > 0]
    assert abs(np.median(voiced) - 100) < 10
    assert res["pass_masks"]["f0_range"].mean() > 0.8
