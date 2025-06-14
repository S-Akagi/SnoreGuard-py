#!/usr/bin/env python3
import logging
import threading

from pythonosc import dispatcher, osc_server, udp_client

from snoreguard.vrc.osc_query_service import OSCQueryService
from snoreguard.vrc.mdns_client import OSCQueryServiceFinder

logger = logging.getLogger(__name__)


class VRChatOSCReceiver:
    """VRChatからのOSCメッセージを受信するクラス"""

    def __init__(self, port, app_instance, log_callback):
        logger.debug(f"VRChatOSCReceiver初期化 - port: {port}")
        self.port = port
        self.app_instance = app_instance
        self.log_callback = log_callback
        self.server = None
        self.is_running = False
        self._server_thread = None

    def start(self):
        """OSCメッセージの受信を開始"""
        logger.debug(f"OSC受信開始要求 - port: {self.port}")
        if self.is_running:
            logger.warning("OSC受信既に実行中")
            return
        try:
            dispatcher_obj = dispatcher.Dispatcher()
            dispatcher_obj.map("/avatar/parameters/MuteSelf", self._mute_handler)
            # SnoreGuard OSC入力ハンドラー
            dispatcher_obj.map(
                "/avatar/parameters/SnoreGuard/ToggleDetection",
                self._toggle_detection_handler,
            )
            dispatcher_obj.map(
                "/avatar/parameters/SnoreGuard/SetNotification",
                self._set_notification_handler,
            )
            dispatcher_obj.map(
                "/avatar/parameters/SnoreGuard/SetAutoMute", self._set_auto_mute_handler
            )
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
        """OSCメッセージの受信を停止"""
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
        """VRChatからのミュート状態変化メッセージを処理"""
        if self.log_callback:
            self.log_callback(
                f"VRChatからマイク状態通知: {'ミュート' if is_muted else 'ミュート解除'} 🎤",
                "vrchat",
            )
        if self.app_instance:
            self.app_instance.on_vrchat_mute_change(is_muted)

    def _toggle_detection_handler(self, address: str, value: bool):
        """VRChatからの検出トグルメッセージを処理"""
        if self.log_callback:
            self.log_callback(
                f"VRChatから検出{'開始' if value else '停止'}通知: {value} 🎵",
                "vrchat",
            )
        if self.app_instance:
            # 現在の状態と異なる場合のみ処理
            if value and not self.app_instance.is_running:
                self.app_instance._start_detection()
            elif not value and self.app_instance.is_running:
                self.app_instance._stop_detection()

    def _set_notification_handler(self, address: str, value: bool):
        """VRChatからの通知設定メッセージを処理"""
        if self.log_callback:
            self.log_callback(
                f"VRChatから通知{'ON' if value else 'OFF'}通知: {value} 🔔",
                "vrchat",
            )
        if self.app_instance:
            self.app_instance.set_notification_from_osc(value)

    def _set_auto_mute_handler(self, address: str, value: bool):
        """VRChatからの自動ミュート設定メッセージを処理"""
        if self.log_callback:
            self.log_callback(
                f"VRChatから自動ミュート{'ON' if value else 'OFF'}通知: {value} 🔇",
                "vrchat",
            )
        if self.app_instance:
            self.app_instance.set_auto_mute_from_osc(value)


class VRCHandler:
    """VRChatとのOSC通信全体を統合管理するメインハンドラークラス"""

    def __init__(self, status_callback, app_instance, log_callback):
        logger.debug("VRCHandler初期化開始")
        self.log_callback = log_callback
        self.app_instance = app_instance
        self.osc_service = OSCQueryService(
            status_callback, app_instance.on_vrchat_mute_change, log_callback
        )
        self.osc_receiver = VRChatOSCReceiver(9001, app_instance, log_callback)
        self.oscquery_finder = OSCQueryServiceFinder(
            self.on_vrchat_discovered, log_callback
        )
        logger.debug("VRCHandler初期化完了")

    def start(self):
        """すべてのVRChat連携サービスを開始"""
        logger.debug("VRCHandler開始")
        self.osc_service.start()
        self.osc_receiver.start()
        self.oscquery_finder.start()
        logger.info("VRCHandler開始完了")

    def stop(self):
        """すべてのVRChat連携サービスを停止"""
        logger.debug("VRCHandler停止")
        self.osc_service.stop()
        self.osc_receiver.stop()
        self.oscquery_finder.stop()
        logger.info("VRCHandler停止完了")

    def toggle_mute(self):
        """VRChat内でマイクのミュート/ミュート解除を実行"""
        logger.debug("VRChatミュートトグル要求")
        self.osc_service.toggle_voice()

    def on_vrchat_discovered(self, service_info):
        """mDNSでVRChatのOSCQueryサービスが発見された時の処理"""
        logger.debug(f"VRChatサービス発見: {service_info}")
        if service_info.get("osc_port"):
            host = (
                service_info["ip_addresses"][0]
                if service_info["ip_addresses"]
                else "127.0.0.1"
            )
            port = service_info["osc_port"]
            logger.info(f"VRChat OSCサービス接続更新: {host}:{port}")

            self._update_osc_service_connection(host, port)
            self.log_callback(f"OSCQuery接続更新: {host}:{port} ✅", "osc")

    def send_feedback(self, address: str, value):
        """VRChatへ状態フィードバックを送信"""
        try:
            if self.osc_service and self.osc_service.osc_client:
                self.osc_service.osc_client.send_message(address, value)
                logger.debug(f"OSCフィードバック送信: {address} = {value}")
            else:
                logger.warning(
                    f"OSCクライアントが初期化されていません: {address} = {value}"
                )
        except Exception as e:
            logger.error(f"OSCフィードバック送信エラー: {e}", exc_info=True)
            if self.log_callback:
                self.log_callback(f"OSCフィードバック送信エラー: {e}", "error")

    def _update_osc_service_connection(self, host: str, port: int):
        """OSCサービスの接続先を更新"""
        self.osc_service.vrchat_host = host
        self.osc_service.vrchat_osc_port = port
        self.osc_service.osc_client = udp_client.SimpleUDPClient(host, port)
        self.osc_service.found_service = True
