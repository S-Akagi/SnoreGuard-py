#!/usr/bin/env python3
import logging
import customtkinter as ctk
import time
from snoreguard.app import SnoreGuardApp
from snoreguard.quick_splash import QuickSplashScreen

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def prepare_app_data(status_callback):
    """アプリケーションデータを準備（UIは作成しない）"""
    try:
        # 段階的初期化
        status_callback("システム初期化中...")
        time.sleep(0.3)

        status_callback("音声エンジン準備中...")
        # librosaのプリコンパイルを実行
        from core.rule_processor import RuleBasedProcessor
        from core.settings import RuleSettings

        # ダミーのプロセッサーでlibrosaをプリコンパイル
        temp_settings = RuleSettings()
        RuleBasedProcessor(temp_settings, lambda: None)

        status_callback("設定読み込み中...")
        time.sleep(0.3)

        status_callback("最終調整中...")
        time.sleep(0.2)

        return True

    except Exception as e:
        logger.error(f"アプリケーション準備エラー: {e}")
        raise


def create_and_run_main_app():
    """メインアプリケーションを作成して実行"""
    try:
        # 新しいTkインスタンスでメインウィンドウを作成
        root = ctk.CTk()
        root.title("SnoreGuard - いびき検出アプリ")

        # ウィンドウの位置を画面中央に設定
        width = 1000
        height = 700
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")

        # SnoreGuardAppを初期化
        SnoreGuardApp(root)

        # ウィンドウを確実に表示
        root.deiconify()  # 表示
        root.state("normal")  # 通常状態に
        root.lift()  # 前面に表示
        root.focus_force()  # フォーカスを設定
        root.attributes("-topmost", True)  # 一時的に最前面に
        root.after(
            200, lambda: root.attributes("-topmost", False)
        )  # 200ms後に最前面を解除

        # 確実に表示されるよう少し待つ
        root.update()

        # メインループ開始
        root.mainloop()

    except Exception as e:
        logger.error(f"メインアプリ作成エラー: {e}")
        raise


def main():
    splash = QuickSplashScreen()

    # 初期化完了フラグ
    initialization_complete = False

    def end_splash_and_show_main():
        """スプラッシュを終了してメインアプリを準備"""
        nonlocal initialization_complete
        if not initialization_complete:
            return
        # スプラッシュのメインループを終了
        splash.splash_root.quit()

    def on_initialization_complete():
        """初期化完了時のコールバック"""
        nonlocal initialization_complete
        initialization_complete = True
        # スプラッシュのメインループ内で終了をスケジュール
        splash.splash_root.after(300, end_splash_and_show_main)

    def initialization_task(status_callback):
        """バックグラウンド初期化タスク"""
        try:
            prepare_app_data(status_callback)
        except Exception as e:
            logger.error(f"初期化エラー: {e}")
            raise

    # 初期化完了コールバックを設定
    splash.on_initialization_complete = on_initialization_complete

    # バックグラウンド初期化を開始
    splash.start_initialization(initialization_task)

    # スプラッシュ画面のメインループ開始
    try:
        splash.run()
    except Exception as e:
        logger.error(f"スプラッシュエラー: {e}")

    # スプラッシュ終了後、メインアプリを作成・実行
    if initialization_complete:
        try:
            # 適切なclose()メソッドを使用してアニメーションを停止
            splash.close()

            # 少し待ってからメインアプリを作成
            time.sleep(0.1)

            create_and_run_main_app()
        except Exception as e:
            logger.error(f"メインアプリエラー: {e}")
    else:
        logger.error("初期化未完了")


if __name__ == "__main__":
    main()
