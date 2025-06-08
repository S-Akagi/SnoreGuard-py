import logging
import threading

from pythonosc import dispatcher, osc_server

from snoreguard.vrc.osc_query_service import OSCQueryService
from snoreguard.vrc.mdns_client import OSCQueryServiceFinder

logger = logging.getLogger(__name__)

# VRChatからのOSCメッセージを受信するクラス
class VRChatOSCReceiver:
    # 初期化
    def __init__(self, port, mute_callback, log_callback):
        logger.debug(f"VRChatOSCReceiver初期化 - port: {port}")
        self.port = port
        self.mute_callback = mute_callback
        self.log_callback = log_callback
        self.server = None
        self.is_running = False
        self._server_thread = None

    # OSC受信開始
    def start(self):
        logger.debug(f"OSC受信開始要求 - port: {self.port}")
        if self.is_running:
            logger.warning("OSC受信既に実行中")
            return
        try:
            dispatcher_obj = dispatcher.Dispatcher()
            dispatcher_obj.map("/avatar/parameters/MuteSelf", self._mute_handler)
            self.server = osc_server.ThreadingOSCUDPServer(
                ("127.0.0.1", self.port), dispatcher_obj
            )
            self._server_thread = threading.Thread(
                target=self.server.serve_forever, daemon=True
            )
            self._server_thread.start()
            self.is_running = True
            logger.info(f"OSC受信開始成功 - port: {self.port}")
            if self.log_callback:
                self.log_callback(f"OSC受信: ポート{self.port}で開始", "osc")
        except Exception as e:
            logger.error(f"OSC受信開始エラー: {e}", exc_info=True)
            if self.log_callback:
                self.log_callback(f"OSC受信エラー: {e}", "error")

    # OSC受信停止
    def stop(self):
        logger.debug("OSC受信停止要求")
        if not self.is_running:
            logger.debug("OSC受信既に停止中")
            return
        self.is_running = False
        if self.server:
            self.server.shutdown()
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.0)
            if self._server_thread.is_alive():
                logger.warning("OSC受信スレッドが正常に終了しませんでした")
        logger.info("OSC受信停止完了")
        if self.log_callback:
            self.log_callback("OSC受信: 停止", "osc")

    # ミュートハンドラ
    def _mute_handler(self, address: str, is_muted: bool):
        if self.log_callback:
            self.log_callback(
                f"VRChatからマイク状態通知: {'ミュート' if is_muted else 'ミュート解除'} 🎤",
                "vrchat",
            )
        if self.mute_callback:
            self.mute_callback(is_muted)

# VRChatとのOSC通信全般を管理するクラス
class VRCHandler:
    # 初期化
    def __init__(self, status_callback, mute_callback, log_callback):
        logger.debug("VRCHandler初期化開始")
        self.log_callback = log_callback
        self.osc_service = OSCQueryService(status_callback, mute_callback, log_callback)
        self.osc_receiver = VRChatOSCReceiver(9001, mute_callback, log_callback)
        self.oscquery_finder = OSCQueryServiceFinder(
            self.on_vrchat_discovered, log_callback
        )
        logger.debug("VRCHandler初期化完了")

    # 開始
    def start(self):
        logger.debug("VRCHandler開始")
        self.osc_service.start()
        self.osc_receiver.start()
        self.oscquery_finder.start()
        logger.info("VRCHandler開始完了")

    # 停止
    def stop(self):
        logger.debug("VRCHandler停止")
        self.osc_service.stop()
        self.osc_receiver.stop()
        self.oscquery_finder.stop()
        logger.info("VRCHandler停止完了")

    # ミュートトグル
    def toggle_mute(self):
        logger.debug("VRChatミュートトグル要求")
        self.osc_service.toggle_voice()

    # VRChatサービス発見
    def on_vrchat_discovered(self, service_info):
        logger.debug(f"VRChatサービス発見: {service_info}")
        if service_info.get("osc_port"):
            host = (
                service_info["ip_addresses"][0]
                if service_info["ip_addresses"]
                else "127.0.0.1"
            )
            port = service_info["osc_port"]
            logger.info(f"VRChat OSCサービス接続更新: {host}:{port}")
            self.osc_service.vrchat_host = host
            self.osc_service.vrchat_osc_port = port
            from pythonosc import udp_client

            self.osc_service.osc_client = udp_client.SimpleUDPClient(host, port)
            self.osc_service.found_service = True
            self.log_callback(f"OSCQuery接続更新: {host}:{port} ✅", "osc")
