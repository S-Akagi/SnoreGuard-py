#!/usr/bin/env python3
"""SnoreGuard エントリポイント。"""

import logging
import sys
import time
import traceback

from snoreguard.logging_setup import (
    install_excepthooks,
    install_tk_report_callback,
    setup_logging,
    show_fatal_error,
)

LOG_FILE = setup_logging()
install_excepthooks()
logger = logging.getLogger(__name__)

import customtkinter as ctk  # noqa: E402 - ログ初期化後に import する

from snoreguard.app import SnoreGuardApp  # noqa: E402
from snoreguard.quick_splash import QuickSplashScreen  # noqa: E402


def prepare_app_data(status_callback):
    """
    アプリケーションの初期化処理を実行
    - 音声分析エンジンのプリコンパイル（librosa/numba の初回 JIT）
    - スプラッシュ画面に進捗を表示
    """
    status_callback("システム初期化中...")
    status_callback("音声エンジン準備中...")
    from core.rule_processor import RuleBasedProcessor
    from core.settings import RuleSettings

    RuleBasedProcessor(RuleSettings(), lambda: None)
    status_callback("設定読み込み中...")
    return True


def create_and_run_main_app():
    """メインアプリケーションウィンドウを作成して実行"""
    root = ctk.CTk()
    install_tk_report_callback(root)
    root.title("SnoreGuard - いびき検出アプリ")
    SnoreGuardApp(root)
    root.deiconify()
    root.lift()
    root.focus_force()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))
    root.update()
    root.mainloop()


def main():
    """
    - スプラッシュ画面の表示とバックグラウンド初期化
    - 初期化完了後にメインアプリケーションウィンドウを表示
    - 失敗時はログに残し、ダイアログで利用者に知らせる
    """
    splash = QuickSplashScreen()
    install_tk_report_callback(splash.splash_root)
    initialization_complete = False

    def end_splash_and_show_main():
        if initialization_complete:
            splash.splash_root.quit()

    def on_initialization_complete():
        nonlocal initialization_complete
        initialization_complete = True
        splash.splash_root.after(300, end_splash_and_show_main)

    splash.on_initialization_complete = on_initialization_complete
    splash.start_initialization(prepare_app_data)
    splash.run()

    if not initialization_complete:
        message = (
            "初期化に失敗しました。音声エンジンの準備中にエラーが発生しています。\n"
            f"ログ: {LOG_FILE}"
        )
        logger.error(message)
        show_fatal_error(message)
        return 1

    splash.close()
    time.sleep(0.1)
    create_and_run_main_app()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # 送出し直した例外は sys.excepthook 側で記録される
        show_fatal_error(
            "SnoreGuard の起動に失敗しました。\n\n"
            f"{traceback.format_exc(limit=3)}\n"
            f"詳細はログを確認してください: {LOG_FILE}"
        )
        raise
