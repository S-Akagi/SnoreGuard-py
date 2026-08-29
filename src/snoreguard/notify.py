"""PC 通知音。Windows 専用の winsound をここに隔離する。"""

import logging
import sys
import threading

logger = logging.getLogger(__name__)


def beep(frequency: int = 1000, duration_ms: int = 200) -> threading.Thread | None:
    """ビープ音を別スレッドで鳴らす。

    - Windows 以外では何もしない（None を返す）
    - 再生失敗は警告ログにとどめ、呼び出し元には伝播させない
    - 戻り値のスレッドはテスト用（join できる）
    """
    if not sys.platform.startswith("win"):
        return None

    def _run() -> None:
        try:
            import winsound

            winsound.Beep(frequency, duration_ms)
        except Exception as e:  # noqa: BLE001 - 通知音の失敗で本処理を止めない
            logger.warning(f"ビープ音の再生に失敗: {e}")

    thread = threading.Thread(target=_run, daemon=True, name="notify-beep")
    thread.start()
    return thread
