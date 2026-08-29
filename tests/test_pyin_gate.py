"""エネルギー閾値によるpyinスキップ（コスト削減）が検出結果を変えないことの確認。

pyin は他の特徴量の数倍のコストがかかり、音声読み取りスレッドと同じスレッドで
動くため、オーバーランすると音声が捨てられる。エネルギー閾値を超えるフレームが
無いチャンクは final_mask が必ず全 False になるので、pyin を省略できる。
"""

import numpy as np

from core.rule_processor import FeatureExtractor, RuleBasedProcessor
from core.settings import RuleSettings

SR, FRAME, HOP = 16000, 800, 200
EXTENDED = SR + (FRAME - HOP)  # 拡張バッファ長（持ち越し 600 サンプル分）


def _tone(num_samples: int, f0: float = 100.0, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(num_samples) / SR
    y = np.zeros(num_samples)
    for k in range(1, 9):
        y += np.sin(2 * np.pi * f0 * k * t) / (k * k)
    y /= np.max(np.abs(y))
    return (y * amplitude).astype(np.float32)


def test_quiet_chunk_skips_pyin_and_yields_zero_f0(monkeypatch):
    """エネルギー閾値を下回るチャンクでは pyin を呼ばず、F0 は全ゼロになる"""
    import core.rule_processor as rp

    calls = []
    monkeypatch.setattr(
        rp.librosa, "pyin", lambda *a, **kw: calls.append(1) or (None, None, None)
    )

    settings = RuleSettings()
    fe = FeatureExtractor(SR, FRAME, HOP, settings)
    quiet = _tone(EXTENDED, amplitude=settings.energy_threshold / 10)
    features = fe.extract_features(quiet)

    assert calls == []  # pyin は呼ばれない
    assert np.all(features["f0"] == 0.0)
    assert np.all(features["voiced_probs"] == 0.0)
    assert len(features["f0"]) == len(features["rms"])


def test_quiet_chunk_final_mask_is_all_false():
    """静かなチャンクの final_mask は全 False（スキップしても結論は同じ）"""
    processor = RuleBasedProcessor(RuleSettings(), lambda: None)
    result = processor.process_audio_chunk(np.zeros(SR, dtype=np.float32))
    assert not np.any(result["final_mask_frames"])


def test_loud_chunk_still_estimates_f0():
    """十分に大きい 100Hz のトーンでは従来どおり F0 が推定される"""
    fe = FeatureExtractor(SR, FRAME, HOP, RuleSettings())
    features = fe.extract_features(_tone(EXTENDED))
    voiced = features["f0"][features["f0"] > 0]
    assert len(voiced) > 0
    assert abs(float(np.median(voiced)) - 100.0) < 10.0
