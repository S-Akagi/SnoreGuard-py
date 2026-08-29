"""共有 RuleSettings が検出エンジンへ届くこと（参照ズレの回帰防止）。

UI 側のメソッドは Tk ルートを作らずに、スタブへ束縛して呼び出す。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.rule_processor import MaskProcessor
from core.settings import FIELD_LABELS, SLIDER_RANGES, RuleSettings
from snoreguard.app import SnoreGuardApp


def _features(rms: float) -> dict:
    """エネルギー以外はすべて既定値の条件を満たす特徴量"""
    return {
        "rms": np.full(10, rms, dtype=np.float32),
        "voiced_probs": np.ones(10, dtype=np.float32),
        "f0": np.full(10, 100.0, dtype=np.float32),
        "spectral_centroid": np.full(10, 400.0, dtype=np.float32),
        "zcr": np.full(10, 0.01, dtype=np.float32),
    }


def _stub_app(shared: RuleSettings) -> SimpleNamespace:
    """apply_rule_settings / _on_rule_setting_change に必要な最小の依存だけを持つスタブ"""
    stub = SimpleNamespace(
        rule_settings=shared,
        rule_setting_vars={},  # _update_rule_settings_ui は空ループになる
        audio_service=MagicMock(),
        add_log=MagicMock(),
        _save_app_settings=MagicMock(),
        periodicity_status_var=MagicMock(),
    )
    # UI 更新も実物を通す（スライダー辞書が空なので副作用はない）
    stub._update_rule_settings_ui = lambda: SnoreGuardApp._update_rule_settings_ui(stub)
    return stub


def test_mask_processor_sees_copy_from_updates():
    shared = RuleSettings(energy_threshold=0.5)
    mp = MaskProcessor(max_frames=10, settings=shared)
    feats = _features(0.1)
    _, final_before = mp.create_masks(feats)
    assert not final_before.any()  # 0.1 < 0.5 なのでエネルギーで落ちる

    shared.copy_from(RuleSettings(energy_threshold=0.05))  # 差し替えではなくコピー
    _, final_after = mp.create_masks(feats)
    assert final_after.all()


def test_apply_rule_settings_reaches_detector_via_shared_object():
    shared = RuleSettings(energy_threshold=0.09)
    mp = MaskProcessor(max_frames=10, settings=shared)
    feats = _features(0.05)
    _, final_before = mp.create_masks(feats)
    assert not final_before.any()  # 0.05 < 0.09

    stub = _stub_app(shared)
    SnoreGuardApp.apply_rule_settings(
        stub,
        RuleSettings(energy_threshold=0.02, periodicity_event_count=6),
        source="テスト",
    )

    # (a) オブジェクトを差し替えず中身だけ更新している
    assert stub.rule_settings is shared
    assert shared.energy_threshold == pytest.approx(0.02)
    assert shared.periodicity_event_count == 6

    # (b) 先に作った検出器が新しい値を見ている
    _, final_after = mp.create_masks(feats)
    assert final_after.all()

    # (c)(d) 周期リセットと保存が一度ずつ呼ばれる
    stub.audio_service.reset_processor_periodicity.assert_called_once()
    stub._save_app_settings.assert_called_once_with(send_feedback=False)

    # 周期カウンタ表示も新しいイベント数へ更新される
    stub.periodicity_status_var.set.assert_called_with("0 / 6")

    # (f) 差分ログにラベル付きで出力される
    logged = " ".join(str(call.args[0]) for call in stub.add_log.call_args_list)
    assert FIELD_LABELS["energy_threshold"] in logged
    assert "テスト" in logged


def test_apply_rule_settings_clamps_out_of_range_values():
    shared = RuleSettings()
    stub = _stub_app(shared)

    SnoreGuardApp.apply_rule_settings(
        stub, RuleSettings(energy_threshold=5.0), source="テスト"
    )

    assert stub.rule_settings is shared
    assert shared.energy_threshold == pytest.approx(
        SLIDER_RANGES["energy_threshold"][1]
    )


def test_apply_rule_settings_logs_when_nothing_changed():
    shared = RuleSettings()
    stub = _stub_app(shared)

    SnoreGuardApp.apply_rule_settings(stub, RuleSettings(), source="リセット")

    logged = " ".join(str(call.args[0]) for call in stub.add_log.call_args_list)
    assert "変更された設定項目はありません" in logged


def test_on_rule_setting_change_pushes_partner_slider():
    shared = RuleSettings()  # f0_min=70, f0_max=150
    stub = _stub_app(shared)
    stub._update_rule_settings_ui = MagicMock()
    label_var = MagicMock()

    SnoreGuardApp._on_rule_setting_change(
        stub, "f0_min_hz", "150", label_var=label_var, is_int=False
    )

    assert stub.rule_settings is shared
    assert shared.f0_min_hz == pytest.approx(150.0)
    assert shared.f0_max_hz >= 170.0  # 20Hz のギャップを確保して押し上げられる
    stub._update_rule_settings_ui.assert_called_once()


def test_on_rule_setting_change_updates_label_when_unconstrained():
    shared = RuleSettings()
    stub = _stub_app(shared)
    stub._update_rule_settings_ui = MagicMock()
    label_var = MagicMock()

    SnoreGuardApp._on_rule_setting_change(
        stub, "energy_threshold", "0.02", label_var=label_var, is_int=False
    )

    assert shared.energy_threshold == pytest.approx(0.02)
    label_var.set.assert_called_once_with("0.02")
    stub._update_rule_settings_ui.assert_not_called()
