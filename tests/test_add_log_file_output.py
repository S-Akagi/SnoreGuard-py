"""add_log() が GUI だけでなくファイルログにも記録することの確認。

夜間の異常（無音・自動再開の断念など）は GUI を閉じると消えてしまうため、
level 引数を logging のレベルへ写してロガーへ転送する。
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from snoreguard.app import SnoreGuardApp


def _stub_app() -> SimpleNamespace:
    """add_log に必要な最小の依存（ウィジェットは無い状態）"""
    return SimpleNamespace(log_text=None)


def test_error_level_reaches_logger_at_error(caplog):
    with caplog.at_level(logging.DEBUG, logger="snoreguard.app"):
        SnoreGuardApp.add_log(_stub_app(), "自動再開を諦めました", "error")
    records = [r for r in caplog.records if r.name == "snoreguard.app"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "自動再開を諦めました" in records[0].getMessage()


def test_warning_level_reaches_logger_at_warning(caplog):
    with caplog.at_level(logging.DEBUG, logger="snoreguard.app"):
        SnoreGuardApp.add_log(_stub_app(), "60秒以上無音です", "warning")
    assert caplog.records[-1].levelno == logging.WARNING


def test_unknown_level_falls_back_to_info(caplog):
    with caplog.at_level(logging.DEBUG, logger="snoreguard.app"):
        SnoreGuardApp.add_log(_stub_app(), "なにか", "unknown-tag")
    assert caplog.records[-1].levelno == logging.INFO


def test_logged_even_when_widget_is_missing(caplog):
    """ウィジェットが破棄済みでも記録は残る"""
    widget = MagicMock()
    widget.winfo_exists.return_value = False
    stub = SimpleNamespace(log_text=widget)
    with caplog.at_level(logging.DEBUG, logger="snoreguard.app"):
        SnoreGuardApp.add_log(stub, "ウィジェットなし", "system")
    assert "ウィジェットなし" in caplog.text
    widget.insert.assert_not_called()
