import logging
import customtkinter as ctk

from snoreguard.app import SnoreGuardApp

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    logger.debug("アプリケーション開始")

    try:
        root = ctk.CTk()
        logger.debug("CustomTkinter初期化完了")

        SnoreGuardApp(root)
        logger.debug("SnoreGuardApp初期化完了")

        logger.debug("メインループ開始")
        root.mainloop()

    except Exception as e:
        logger.error(f"アプリケーション実行中にエラー: {e}", exc_info=True)
        raise
    finally:
        logger.debug("アプリケーション終了")


if __name__ == "__main__":
    main()
