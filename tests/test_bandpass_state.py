import numpy as np

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings


def test_filter_state_carries_across_chunks():
    sr = 16000
    t = np.arange(sr * 2) / sr
    signal = (0.3 * np.sin(2 * np.pi * 100 * t)).astype(np.float32)
    proc = RuleBasedProcessor(RuleSettings(), lambda: None)
    assert not np.any(proc._zi)  # 初期状態はゼロ
    r1 = proc.process_audio_chunk(signal[:sr])
    assert np.any(proc._zi)  # 1 チャンク処理後は状態が残る
    r2 = proc.process_audio_chunk(signal[sr:])
    rms1 = r1["analysis_results"]["rms"]
    rms2 = r2["analysis_results"]["rms"]
    # フレーム 2（サンプル 0..800、端のゼロ埋めを含まない）が定常値に近いこと。
    # 状態を引き継がない旧実装では過渡応答で約 0.91 倍に落ちる。
    assert rms2[2] > 0.95 * np.median(rms1[10:70])


def test_reset_clears_filter_state():
    proc = RuleBasedProcessor(RuleSettings(), lambda: None)
    proc.process_audio_chunk(
        np.random.default_rng(0).normal(0, 0.1, 16000).astype(np.float32)
    )
    proc.reset_periodicity()
    assert not np.any(proc._zi)
