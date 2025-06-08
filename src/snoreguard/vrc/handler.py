import logging
import threading

from pythonosc import dispatcher, osc_server

from snoreguard.vrc.osc_query_service import OSCQueryService
from snoreguard.vrc.mdns_client import OSCQueryServiceFinder

logger = logging.getLogger(__name__)


class VRChatOSCReceiver:
    """
    VRChatからのOSCメッセージを受信するクラス
    - VRChatのアバターパラメータ「MuteSelf」を監視し、
    - ユーザーのマイク状態の変化をリアルタイムで検知する
    """

    def __init__(self, port, mute_callback, log_callback):
        """
        VRChatOSCReceiverを初期化
        - port: OSCメッセージを受信するポート番号
        - mute_callback: ミュート状態変化時のコールバック関数
        - log_callback: ログ出力用コールバック関数
        """
        logger.debug(f"VRChatOSCReceiver初期化 - port: {port}")
        self.port = port
        self.mute_callback = mute_callback
        self.log_callback = log_callback
        self.server = None
        self.is_running = False
        self._server_thread = None

    def start(self):
        """
        OSCメッセージの受信を開始
        - マルチスレッドOSCサーバーを起動し、VRChatからの
        - アバターパラメータ更新メッセージを待機する
        """
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

    def stop(self):
        """
        OSCメッセージの受信を停止
        - サーバーをシャットダウンし、スレッドの終了を待機する
        """
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

    def _mute_handler(self, address: str, is_muted: bool):
        """
        VRChatからのミュート状態変化メッセージを処理
        - address: OSCアドレス（/avatar/parameters/MuteSelf）
        - is_muted: ミュート状態（True=ミュート、False=ミュート解除）
        """
        if self.log_callback:
            self.log_callback(
                f"VRChatからマイク状態通知: {'ミュート' if is_muted else 'ミュート解除'} 🎤",
                "vrchat",
            )
        if self.mute_callback:
            self.mute_callback(is_muted)


class VRCHandler:
    """
    VRChatとのOSC通信全体を統合管理するメインハンドラークラス。
    - OSCQueryサービス、OSCメッセージ受信、mDNSサービス探索などの
      VRChat連携機能を一元管理し、いびき検出時の自動ミュート機能を提供
    """

    def __init__(self, status_callback, mute_callback, log_callback):
        """
        VRCHandlerを初期化
        - status_callback: VRChat接続状態変化時のコールバック関数
        - mute_callback: ミュート状態変化時のコールバック関数
        - log_callback: ログ出力用コールバック関数
        """
        logger.debug("VRCHandler初期化開始")
        self.log_callback = log_callback
        # VRChat連携の主要コンポーネントを初期化
        self.osc_service = OSCQueryService(status_callback, mute_callback, log_callback)
        self.osc_receiver = VRChatOSCReceiver(
            9001, mute_callback, log_callback
        )  # 標準ポート使用
        self.oscquery_finder = OSCQueryServiceFinder(
            self.on_vrchat_discovered, log_callback
        )
        logger.debug("VRCHandler初期化完了")

    def start(self):
        """
        - すべてのVRChat連携サービスを開始
        - OSCQueryサービス、OSCメッセージ受信、mDNSサービス探索を同時に開始
        """
        logger.debug("VRCHandler開始")
        self.osc_service.start()
        self.osc_receiver.start()
        self.oscquery_finder.start()
        logger.info("VRCHandler開始完了")

    def stop(self):
        """
        - すべてのVRChat連携サービスを停止
        - 各サービスの停止処理を順序実行し、リソースをクリーンアップ
        """
        logger.debug("VRCHandler停止")
        self.osc_service.stop()
        self.osc_receiver.stop()
        self.oscquery_finder.stop()
        logger.info("VRCHandler停止完了")

    def toggle_mute(self):
        """
        VRChat内でマイクのミュート/ミュート解除を実行
        - いびき検出時に自動的に呼び出され、VRChatのVoiceボタンを
        - シミュレートしてマイクを一時的にミュートする
        """
        logger.debug("VRChatミュートトグル要求")
        self.osc_service.toggle_voice()

    def on_vrchat_discovered(self, service_info):
        """
        mDNSでVRChatのOSCQueryサービスが発見された時の処理
        - 発見されたサービス情報からOSCポートを取得し、
          OSCクライアントの接続先を動的に更新する
        - service_info: mDNSで発見されたサービスの情報
        """
        logger.debug(f"VRChatサービス発見: {service_info}")
        if service_info.get("osc_port"):
            # 発見されたサービス情報から接続先を取得
            host = (
                service_info["ip_addresses"][0]
                if service_info["ip_addresses"]
                else "127.0.0.1"  # フォールバック先
            )
            port = service_info["osc_port"]
            logger.info(f"VRChat OSCサービス接続更新: {host}:{port}")

            # OSCサービスの接続先を動的更新
            self.osc_service.vrchat_host = host
            self.osc_service.vrchat_osc_port = port
            from pythonosc import udp_client

            self.osc_service.osc_client = udp_client.SimpleUDPClient(host, port)
            self.osc_service.found_service = True
            self.log_callback(f"OSCQuery接続更新: {host}:{port} ✅", "osc")
