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


def test_setup_logging_without_stderr_adds_only_file_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    logging_setup.setup_logging(log_dir=tmp_path)
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.FileHandler)


def test_get_log_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logging_setup.get_log_dir() == tmp_path / "SnoreGuard" / "logs"


def test_install_excepthooks_logs_thread_exception(tmp_path):
    import threading

    log_file = logging_setup.setup_logging(log_dir=tmp_path)
    logging_setup.install_excepthooks()

    def boom():
        raise ValueError("thread failure")

    t = threading.Thread(target=boom)
    t.start()
    t.join()
    for h in logging.getLogger().handlers:
        h.flush()
    assert "thread failure" in log_file.read_text(encoding="utf-8")
