import numpy as np

from core.rule_processor import MaskProcessor
from core.settings import RuleSettings


def test_mask_processor_sees_copy_from_updates():
    shared = RuleSettings(energy_threshold=0.5)
    mp = MaskProcessor(max_frames=10, settings=shared)
    feats = {
        "rms": np.full(10, 0.1, dtype=np.float32),
        "voiced_probs": np.ones(10, dtype=np.float32),
        "f0": np.full(10, 100.0, dtype=np.float32),
        "spectral_centroid": np.full(10, 400.0, dtype=np.float32),
        "zcr": np.full(10, 0.01, dtype=np.float32),
    }
    _, final_before = mp.create_masks(feats)
    assert not final_before.any()  # 0.1 < 0.5 なのでエネルギーで落ちる

    shared.copy_from(RuleSettings(energy_threshold=0.05))  # 差し替えではなくコピー
    _, final_after = mp.create_masks(feats)
    assert final_after.all()
