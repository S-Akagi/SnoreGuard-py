import numpy as np
import pytest

from core.rule_processor import (
    FeatureExtractionError,
    FeatureExtractor,
    RuleBasedProcessor,
)
from core.settings import RuleSettings


def test_feature_extractor_raises_on_invalid_f0_range():
    fe = FeatureExtractor(16000, 800, 200, RuleSettings(f0_min_hz=150, f0_max_hz=100))
    with pytest.raises(FeatureExtractionError):
        fe.extract_features(np.zeros(16000, dtype=np.float32))


def test_process_audio_chunk_skips_chunk_instead_of_crashing():
    # sanitized を通さない生の不正値（JSON 手編集などを想定）
    settings = RuleSettings(f0_min_hz=150, f0_max_hz=100)
    processor = RuleBasedProcessor(settings, lambda: None)
    result = processor.process_audio_chunk(np.zeros(16000, dtype=np.float32))
    assert result == {}


def test_process_audio_chunk_returns_81_frames_for_one_second():
    processor = RuleBasedProcessor(RuleSettings(), lambda: None)
    result = processor.process_audio_chunk(np.zeros(16000, dtype=np.float32))
    assert len(result["final_mask_frames"]) == 81
