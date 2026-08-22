import logging
import sys

from snoreguard import logging_setup


def test_setup_logging_writes_to_file(tmp_path):
    log_file = logging_setup.setup_logging(log_dir=tmp_path)
    logging.getLogger("test.x").info("こんにちは")
    for h in logging.getLogger().handlers:
        h.flush()
    assert log_file == tmp_path / "snoreguard.log"
    assert "こんにちは" in log_file.read_text(encoding="utf-8")
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)
    )
    assert handler.encoding == "utf-8"
    assert handler.maxBytes == 1_000_000
    assert handler.backupCount == 3


def test_setup_logging_without_stderr_adds_only_file_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    logging_setup.setup_logging(log_dir=tmp_path)
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.FileHandler)


def test_get_log_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logging_setup.get_log_dir() == tmp_path / "SnoreGuard" / "logs"


def test_install_excepthooks_logs_thread_exception(tmp_path, monkeypatch):
    import threading

    log_file = logging_setup.setup_logging(log_dir=tmp_path)
    # フックはグローバル状態なので、テスト終了時に元へ戻す
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    logging_setup.install_excepthooks()

    def boom():
        raise ValueError("thread failure")

    t = threading.Thread(target=boom)
    t.start()
    t.join()
    for h in logging.getLogger().handlers:
        h.flush()
    assert "thread failure" in log_file.read_text(encoding="utf-8")


def test_show_fatal_error_reuses_live_default_root(monkeypatch):
    """既存の Tk ルートがあるときは作り直さず、それを parent にする。"""
    import tkinter as tk
    from tkinter import messagebox

    class FakeRoot:
        def __init__(self):
            self.destroyed = False

        def winfo_exists(self):
            return True

        def destroy(self):
            self.destroyed = True

    fake_root = FakeRoot()
    monkeypatch.setattr(tk, "_default_root", fake_root, raising=False)

    created = []

    def fake_tk():
        created.append(True)
        raise RuntimeError("既存ルートがあるのに Tk() を作ってはいけない")

    monkeypatch.setattr(tk, "Tk", fake_tk)

    calls = {}

    def fake_showerror(title, message, **kwargs):
        calls["parent"] = kwargs.get("parent")

    monkeypatch.setattr(messagebox, "showerror", fake_showerror)

    assert logging_setup.show_fatal_error("x") is None
    assert created == []
    assert calls["parent"] is fake_root
    assert fake_root.destroyed is False


def test_show_fatal_error_never_raises(monkeypatch):
    """Tk が使えなくても例外を出さずに戻る。"""
    import tkinter as tk

    monkeypatch.setattr(tk, "_default_root", None, raising=False)

    def fake_tk():
        raise RuntimeError("no display")

    monkeypatch.setattr(tk, "Tk", fake_tk)

    assert logging_setup.show_fatal_error("x") is None
