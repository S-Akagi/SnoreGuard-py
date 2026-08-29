"""ログ出力と未捕捉例外の記録。

windowed exe（console=False）では sys.stderr が None になり、標準の
logging.basicConfig では全ログが消える。ここでは常にファイルへ書き、
stderr があるときだけ併せて出力する。
"""

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_log_dir() -> Path:
    """ログディレクトリ。Windows は %LOCALAPPDATA%\\SnoreGuard\\logs。"""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "SnoreGuard" / "logs"
    return Path.home() / ".snoreguard" / "logs"


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    """ルートロガーを構成し、ログファイルのパスを返す。"""
    log_dir = log_dir or get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "snoreguard.log"

    formatter = logging.Formatter(LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    logging.getLogger(__name__).info(f"ログ出力先: {log_file}")
    return log_file


def install_excepthooks() -> None:
    """メインスレッド・サブスレッドの未捕捉例外をログに残す。"""
    log = logging.getLogger("snoreguard.unhandled")

    def _sys_hook(exc_type, exc_value, exc_tb):
        log.critical("未捕捉例外", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args: threading.ExceptHookArgs):
        name = args.thread.name if args.thread else "?"
        log.critical(
            f"スレッド {name} で未捕捉例外",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def install_tk_report_callback(root) -> None:
    """Tk コールバック内の例外（通常は stderr に出るだけ）をログへ。"""
    log = logging.getLogger("snoreguard.tk")

    def _report(exc_type, exc_value, exc_tb):
        log.error("Tk コールバック内で例外", exc_info=(exc_type, exc_value, exc_tb))

    root.report_callback_exception = _report


def _live_default_root():
    """生存している既定の Tk ルートを返す。無ければ None。"""
    try:
        import tkinter as tk

        root = getattr(tk, "_default_root", None)
        if root is not None and root.winfo_exists():
            return root
    except Exception:  # noqa: BLE001 - 破棄済みなら新しく作る
        return None
    return None


def show_fatal_error(message: str) -> None:
    """起動失敗などをダイアログで知らせる。Tk が使えない場合は黙って戻る。

    すでに Tk ルートがある（メインウィンドウ生成後の失敗など）場合はそれを
    親にする。無い場合だけ隠しルートを作り、後で破棄する。
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = _live_default_root()
        created = root is None
        if created:
            root = tk.Tk()
            root.withdraw()
        try:
            messagebox.showerror("SnoreGuard - 起動エラー", message, parent=root)
        finally:
            if created:
                root.destroy()
    except Exception:  # noqa: BLE001 - ここで失敗しても打つ手がない
        pass
