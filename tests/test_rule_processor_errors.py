import numpy as np
import pytest

from core.rule_processor import (
    FeatureExtractionError,
    FeatureExtractor,
    RuleBasedProcessor,
)
from core.settings import RuleSettings


def test_feature_extractor_wraps_errors(monkeypatch):
    import core.rule_processor as rp

    def boom(*args, **kwargs):
        raise ValueError("pyin failed")

    monkeypatch.setattr(rp.librosa, "pyin", boom)
    fe = FeatureExtractor(16000, 800, 200, RuleSettings())
    with pytest.raises(FeatureExtractionError):
        fe.extract_features(np.zeros(16000, dtype=np.float32))


def test_process_audio_chunk_skips_chunk_instead_of_crashing(monkeypatch):
    import core.rule_processor as rp

    processor = RuleBasedProcessor(RuleSettings(), lambda: None)

    def boom(*args, **kwargs):
        raise ValueError("pyin failed")

    monkeypatch.setattr(rp.librosa, "pyin", boom)
    assert processor.process_audio_chunk(np.zeros(16000, dtype=np.float32)) == {}


def test_process_audio_chunk_returns_80_frames_for_one_second():
    processor = RuleBasedProcessor(RuleSettings(), lambda: None)
    result = processor.process_audio_chunk(np.zeros(16000, dtype=np.float32))
    assert len(result["final_mask_frames"]) == 80
