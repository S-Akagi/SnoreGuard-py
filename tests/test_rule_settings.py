import math

from core.settings import (
    F0_MIN_GAP_HZ,
    FIELD_LABELS,
    SLIDER_RANGES,
    RuleSettings,
    format_setting_value,
)


def test_slider_ranges_cover_all_fields():
    from dataclasses import fields

    names = {f.name for f in fields(RuleSettings)}
    assert set(SLIDER_RANGES) == names
    assert set(FIELD_LABELS) == names


def test_copy_from_keeps_identity():
    a = RuleSettings()
    b = RuleSettings(energy_threshold=0.05, periodicity_event_count=7)
    a.copy_from(b)
    assert a.energy_threshold == 0.05
    assert a.periodicity_event_count == 7
    assert a is not b


def test_from_dict_coerces_and_falls_back():
    s = RuleSettings.from_dict(
        {"energy_threshold": "0.02", "periodicity_event_count": "abc", "unknown": 1}
    )
    assert s.energy_threshold == 0.02
    assert s.periodicity_event_count == RuleSettings().periodicity_event_count
    assert isinstance(s.periodicity_event_count, int)


def test_sanitized_clamps_to_slider_range():
    s = RuleSettings(energy_threshold=5.0, spectral_centroid_threshold=-10).sanitized()
    assert s.energy_threshold == SLIDER_RANGES["energy_threshold"][1]
    assert (
        s.spectral_centroid_threshold == SLIDER_RANGES["spectral_centroid_threshold"][0]
    )


def test_sanitized_enforces_f0_order():
    s = RuleSettings(f0_min_hz=150, f0_max_hz=100).sanitized()
    assert s.f0_min_hz < s.f0_max_hz
    s2 = RuleSettings(f0_min_hz=150, f0_max_hz=150).sanitized()
    assert s2.f0_min_hz < s2.f0_max_hz


def test_sanitized_enforces_duration_and_interval_order():
    s = RuleSettings(min_duration_seconds=1.0, max_duration_seconds=0.5).sanitized()
    assert s.min_duration_seconds <= s.max_duration_seconds
    s2 = RuleSettings(
        min_event_interval_seconds=9.0, max_event_interval_seconds=5.0
    ).sanitized()
    assert s2.min_event_interval_seconds <= s2.max_event_interval_seconds


def test_validate_reports_problems():
    assert RuleSettings().validate() == []
    problems = RuleSettings(
        f0_min_hz=200, f0_max_hz=100, periodicity_event_count=0
    ).validate()
    assert any("f0" in p for p in problems)
    assert any("periodicity_event_count" in p for p in problems)


def test_diff_lists_changed_fields_only():
    old = RuleSettings()
    new = RuleSettings(zcr_threshold=0.1)
    d = old.diff(new)
    assert d == [("zcr_threshold", FIELD_LABELS["zcr_threshold"], 0.06, 0.1)]


def test_from_dict_rejects_non_finite():
    default = RuleSettings()
    for raw in ("nan", "inf", "-inf", float("nan"), float("inf")):
        s = RuleSettings.from_dict({"energy_threshold": raw})
        assert s.energy_threshold == default.energy_threshold


def test_from_dict_rejects_bool():
    default = RuleSettings()
    s = RuleSettings.from_dict(
        {"periodicity_event_count": True, "energy_threshold": False}
    )
    assert s.periodicity_event_count == default.periodicity_event_count
    assert s.energy_threshold == default.energy_threshold


def test_sanitized_replaces_non_finite_with_default():
    lo, hi, _step = SLIDER_RANGES["energy_threshold"]
    for bad in (float("nan"), float("inf"), float("-inf")):
        value = RuleSettings(energy_threshold=bad).sanitized().energy_threshold
        assert math.isfinite(value)
        assert lo <= value <= hi
        assert value == RuleSettings().energy_threshold


def test_sanitized_uses_declared_field_types():
    s = RuleSettings(f0_min_hz=150, f0_max_hz=100).sanitized()
    assert isinstance(s.f0_min_hz, float)
    assert isinstance(s.f0_max_hz, float)
    s2 = RuleSettings(periodicity_event_count=4.7).sanitized()
    assert isinstance(s2.periodicity_event_count, int)
    assert s2.periodicity_event_count == 5


def test_validate_reports_insufficient_f0_gap():
    problems = RuleSettings(f0_min_hz=140.0, f0_max_hz=145.0).validate()
    assert problems
    assert any("f0" in p for p in problems)


def test_valid_settings_are_unchanged_by_sanitized():
    default = RuleSettings()
    assert default.validate() == []
    assert default.sanitized() == default

    custom = RuleSettings(
        energy_threshold=0.02,
        f0_min_hz=80.0,
        f0_max_hz=200.0,
        periodicity_event_count=5,
    )
    assert custom.validate() == []
    assert custom.sanitized() == custom


def test_format_setting_value():
    assert format_setting_value(100.0) == "100"
    assert format_setting_value(0.015) == "0.015"
    assert format_setting_value(4) == "4"


def test_f0_min_gap_constant():
    assert F0_MIN_GAP_HZ == 20.0


def test_f0_min_slider_reaches_pyin_lower_bound():
    """F0最小値は pyin の探索下限 50Hz まで下げられる（低い声のいびき対策）"""
    from core.constants import PYIN_FMIN_HZ

    lo, hi, _step = SLIDER_RANGES["f0_min_hz"]
    assert lo == PYIN_FMIN_HZ
    settings = RuleSettings(f0_min_hz=50.0, f0_max_hz=150.0)
    assert settings.validate() == []
    assert settings.sanitized().f0_min_hz == 50.0


def test_f0_min_below_slider_range_is_clamped():
    assert RuleSettings(f0_min_hz=10.0).sanitized().f0_min_hz == 50.0
