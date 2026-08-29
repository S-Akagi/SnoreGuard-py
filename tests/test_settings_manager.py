import json

from snoreguard.settings_manager import SettingsManager

DEFAULTS = {"a": 1, "nested": {"b": 2}}


def test_roundtrip(tmp_path):
    sm = SettingsManager(tmp_path / "s.json")
    sm.save({"a": 5, "nested": {"b": 9}})
    loaded = SettingsManager(tmp_path / "s.json").load(DEFAULTS)
    assert loaded == {"a": 5, "nested": {"b": 9}}
    assert not (tmp_path / "s.tmp").exists()


def test_missing_file_returns_defaults_copy(tmp_path):
    sm = SettingsManager(tmp_path / "s.json")
    loaded = sm.load(DEFAULTS)
    assert loaded == DEFAULTS
    assert loaded is not DEFAULTS
    assert sm.last_error is None


def test_non_utf8_file_is_backed_up_and_defaults_used(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes('{"mic_device_name": "マイク"}'.encode("shift_jis"))
    sm = SettingsManager(path)
    loaded = sm.load(DEFAULTS)
    assert loaded == DEFAULTS
    assert sm.last_error is not None
    assert sm.backup_path is not None and sm.backup_path.exists()
    assert not path.exists()


def test_non_dict_json_is_backed_up(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    sm = SettingsManager(path)
    assert sm.load(DEFAULTS) == DEFAULTS
    assert sm.last_error is not None


def test_invalid_json_is_backed_up(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    sm = SettingsManager(path)
    assert sm.load(DEFAULTS) == DEFAULTS
    assert sm.backup_path.name.endswith(".bak")
