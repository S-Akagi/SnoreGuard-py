import logging
import threading
import time
from collections.abc import Callable

from pythonosc import udp_client

logger = logging.getLogger(__name__)

# VRChat標準OSC仕様に準拠したOSCサービス
class OSCQueryService:
    # 初期化
    def __init__(
        self,
        status_callback: Callable[[bool, str], None],
        mute_status_callback: Callable[[bool], None],
        log_callback: Callable[[str, str], None],
    ):
        logger.debug("OSCQueryService初期化")
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.mute_status_callback = mute_status_callback

        self.is_running = False # 実行中フラグ
        self._discovery_thread: threading.Thread | None = None # 発見スレッド

        self.vrchat_host: str | None = None # VRChatホスト
        self.vrchat_osc_port: int | None = None # VRChat OSCポート
        self.found_service = False # サービス発見フラグ
        self.osc_client: udp_client.SimpleUDPClient | None = None # OSCクライアント
        logger.debug("OSCQueryService初期化完了")

    # 開始
    def start(self):
        logger.debug("OSCQueryService開始要求")
        if self.is_running:
            logger.warning("OSCQueryService既に実行中")
            return

        self.is_running = True
        self._discovery_thread = threading.Thread(
            target=self._run_discovery, daemon=True, name="OSCQueryService-Discovery"
        )
        self._discovery_thread.start()
        logger.info("OSCQueryService開始完了")
        self.log_callback("OSC: VRChat標準OSC接続を開始しました。", "system")

    # 停止
    def stop(self):
        logger.debug("OSCQueryService停止要求")
        self.is_running = False

        if self._discovery_thread and self._discovery_thread.is_alive():
            self._discovery_thread.join(timeout=2.0)
            if self._discovery_thread.is_alive():
                self.log_callback("OSC: 発見スレッドがタイムアウトしました", "warning")

        self.osc_client = None
        self._discovery_thread = None
        logger.info("OSCQueryService停止完了")
        self.log_callback("OSC: サービスを停止しました。", "system")

    # 発見ループ
    def _run_discovery(self):
        logger.debug("発見ループ開始")
        try:
            self.status_callback(False, "VRChat標準OSC接続中...")
            success = self._try_fallback_connection()

            if success:
                logger.info("VRChat標準OSC接続成功")
                self.log_callback("OSC: VRChat標準OSC接続が成功しました。", "system")
                sleep_interval = 10
                while self.is_running and self.found_service:
                    for _ in range(sleep_interval):
                        if not self.is_running:
                            break
                        time.sleep(1)
            else:
                logger.warning("VRChat標準OSC接続失敗")
                self.log_callback("OSC: VRChat標準OSC接続に失敗しました。", "warning")
                self.status_callback(False, "VRChat接続失敗")

        except Exception as e:
            logger.error(f"OSC接続中にエラー: {e}", exc_info=True)
            self.log_callback(f"OSC: 接続中にエラー: {e}", "error")
            self.status_callback(False, "VRChat接続エラー")

    # フォールバック接続試行
    def _try_fallback_connection(self) -> bool:
        logger.debug("VRChat標準OSC接続試行")
        try:
            host, port = "127.0.0.1", 9000
            logger.debug(f"OSC接続試行: {host}:{port}")
            self.log_callback(
                f"OSC: VRChat標準OSCポートで接続試行 - {host}:{port}", "info"
            )
            self.vrchat_host = host
            self.vrchat_osc_port = port
            self.osc_client = udp_client.SimpleUDPClient(host, port)
            self.found_service = True
            self.status_callback(True, f"VRChat OSC接続 ({host}:{port})")
            logger.info(f"OSC接続成功: {host}:{port}")
            return True
        except Exception as e:
            logger.error(f"OSC接続エラー: {e}", exc_info=True)
            self.log_callback(f"OSC: VRChat標準OSC接続エラー: {e}", "error")
            return False

    # 音声トグル
    def toggle_voice(self):
        logger.debug("OSC Voiceトグル要求")
        if not self.osc_client or not self.found_service:
            logger.warning("OSCクライアント未接続")
            self.log_callback("OSC: VRChat未接続のためミュート操作不可", "warning")
            return

        try:
            # メッセージ送信の効率化
            logger.debug("OSC Voiceメッセージ送信: 1")
            self.osc_client.send_message("/input/Voice", 1)
            # タイマーを再利用してリセットをスケジュール
            reset_timer = threading.Timer(0.1, self._reset_voice_input)
            reset_timer.daemon = True
            reset_timer.start()
            logger.debug("OSC Voiceトグル実行完了")

        except Exception as e:
            logger.error(f"OSC Voiceトグルエラー: {e}", exc_info=True)
            self.log_callback(f"OSC: Voiceトグルエラー: {e}", "error")

    # 音声入力リセット
    def _reset_voice_input(self):
        if self.osc_client and self.is_running:
            try:
                logger.debug("OSC Voiceメッセージ送信: 0")
                self.osc_client.send_message("/input/Voice", 0)
            except Exception as e:
                # サービス停止中のエラーは無視
                if self.is_running:
                    logger.error(f"OSC Voiceリセットエラー: {e}", exc_info=True)
                    self.log_callback(f"OSC: Voiceリセットエラー: {e}", "error")
