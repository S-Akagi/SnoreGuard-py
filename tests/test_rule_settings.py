from core.settings import FIELD_LABELS, SLIDER_RANGES, RuleSettings


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
