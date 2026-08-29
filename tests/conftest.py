"""テスト間でグローバルなロギング設定が漏れないようにする。

logging_setup.setup_logging() はルートロガーのハンドラを差し替え、
pytest のキャプチャハンドラを閉じてしまう。各テストの前後で
ルートロガーのハンドラとレベルを退避・復元し、実行順に依存しないようにする。
"""

import logging

import pytest


@pytest.fixture(autouse=True)
def _isolate_root_logger():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in saved_handlers:
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001 - 後始末なので失敗しても続行
                    pass
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
