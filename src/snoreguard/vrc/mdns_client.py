import logging
import socket
import struct
import threading
import time
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)

# mDNSレコードを表現するクラス
class MDNSRecord:
    # 初期化
    def __init__(self, name: str, rtype: int, rclass: int, ttl: int, data: bytes):
        self.name = name
        self.rtype = rtype
        self.rclass = rclass
        self.ttl = ttl
        self.data = data

# 軽量mDNSクライアント実装
class MDNSClient:
    MDNS_PORT = 5353 # mDNSポート
    MDNS_GROUP = "224.0.0.251" # mDNSグループ

    # DNSレコードタイプ
    TYPE_A = 1 # Aレコード
    TYPE_PTR = 12 # PTRレコード
    TYPE_TXT = 16 # TXTレコード
    TYPE_SRV = 33 # SRVレコード

    # 初期化
    def __init__(self, service_callback: Optional[Callable] = None):
        logger.debug("MDNSClient初期化")
        self.socket = None # ソケット
        self.running = False # 実行中フラグ
        self.thread = None # スレッド
        self.service_callback = service_callback # サービスコールバック
        self.discovered_services: Dict[str, Dict] = {} # 発見したサービス

    # mDNS受信を開始
    def start(self):
        logger.debug("mDNSクライアント開始")
        if self.running:
            logger.debug("mDNSクライアント既に実行中")
            return

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Windowsでの互換性のためにSO_REUSEPORTは条件付きで設定
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # WindowsではSO_REUSEPORTが利用できない

            self.socket.bind(("", self.MDNS_PORT))

            # マルチキャストグループに参加
            mreq = struct.pack(
                "4sl", socket.inet_aton(self.MDNS_GROUP), socket.INADDR_ANY
            )
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            self.running = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            logger.info(f"mDNSクライアント開始成功 - ポート: {self.MDNS_PORT}")

        except Exception as e:
            logger.error(f"mDNS開始エラー: {e}", exc_info=True)
            raise Exception(f"mDNS開始エラー: {e}")

    # mDNS受信を停止
    def stop(self):
        logger.debug("mDNSクライアント停止")
        self.running = False
        if self.socket:
            try:
                # マルチキャストグループから脱退
                mreq = struct.pack(
                    "4sl", socket.inet_aton(self.MDNS_GROUP), socket.INADDR_ANY
                )
                self.socket.setsockopt(
                    socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq
                )
            except Exception:
                pass
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=1.0)
            if self.thread.is_alive():
                logger.warning("mDNSスレッドが正常に終了しませんでした")
        logger.info("mDNSクライアント停止完了")

    # 特定のサービスタイプをクエリ
    def query_service(self, service_type: str):
        if not self.socket:
            return

        try:
            query = self._build_query(service_type)
            self.socket.sendto(query, (self.MDNS_GROUP, self.MDNS_PORT))
        except Exception:
            pass  # クエリ送信エラーは無視

    # mDNSパケット受信ループ
    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.socket.recvfrom(4096)
                self._parse_mdns_response(data, addr[0])
            except socket.timeout:
                continue
            except Exception:
                if self.running:
                    time.sleep(0.1)

    # mDNSクエリパケットを構築
    def _build_query(self, service_type: str) -> bytes:
        # DNS Header
        header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)  # ID=0, QR=0, OPCODE=0, etc.

        # Question Section
        question = self._encode_name(service_type)
        question += struct.pack("!HH", self.TYPE_PTR, 1)  # TYPE=PTR, CLASS=IN

        return header + question

    # DNS名前形式にエンコード
    def _encode_name(self, name: str) -> bytes:
        result = b""
        for part in name.split("."):
            if part:
                result += struct.pack("!B", len(part)) + part.encode("ascii")
        result += b"\x00"  # 終端
        return result

    # mDNS応答パケットを解析
    def _parse_mdns_response(self, data: bytes, src_ip: str):
        try:
            if len(data) < 12:
                return

            # DNSヘッダーを解析
            header = struct.unpack("!HHHHHH", data[:12])
            flags = header[1]

            # 応答パケットのみ処理 (QR bit = 1)
            if not (flags & 0x8000):
                return

            questions = header[2]
            answers = header[3]
            authorities = header[4]
            additionals = header[5]

            offset = 12

            # Questionセクションをスキップ
            for _ in range(questions):
                name, offset = self._parse_name(data, offset)
                offset += 4  # TYPE + CLASS

            # Answerセクションを解析
            records = []
            for _ in range(answers + authorities + additionals):
                record, offset = self._parse_resource_record(data, offset)
                if record:
                    records.append(record)

            self._process_service_records(records, src_ip)

        except Exception:
            pass  # パケット解析エラーは無視

    # DNS名前を解析
    def _parse_name(self, data: bytes, offset: int) -> tuple[str, int]:
        parts = []
        original_offset = offset
        jumped = False

        while offset < len(data):
            length = data[offset]

            if length == 0:
                offset += 1
                break
            elif length & 0xC0 == 0xC0:  # 圧縮ポインタ
                if not jumped:
                    original_offset = offset + 2
                    jumped = True
                pointer = struct.unpack("!H", data[offset : offset + 2])[0] & 0x3FFF
                offset = pointer
                continue
            else:
                offset += 1
                if offset + length <= len(data):
                    parts.append(
                        data[offset : offset + length].decode("ascii", errors="ignore")
                    )
                offset += length

        return ".".join(parts), original_offset if jumped else offset

    # リソースレコードを解析
    def _parse_resource_record(
        self, data: bytes, offset: int
    ) -> tuple[Optional[MDNSRecord], int]:
        try:
            name, offset = self._parse_name(data, offset)

            if offset + 10 > len(data):
                return None, offset

            rtype, rclass, ttl, rdlen = struct.unpack(
                "!HHIH", data[offset : offset + 10]
            )
            offset += 10

            if offset + rdlen > len(data):
                return None, offset

            rdata = data[offset : offset + rdlen]
            offset += rdlen

            return MDNSRecord(name, rtype, rclass, ttl, rdata), offset

        except Exception:
            return None, offset

    # サービスレコードを処理してOSCQueryサービスを特定
    def _process_service_records(self, records: List[MDNSRecord], src_ip: str):
        oscquery_services = {}

        # PTRレコードからサービス名を取得
        for record in records:
            if record.rtype == self.TYPE_PTR and "_oscjson._tcp.local" in record.name:
                try:
                    service_name, _ = self._parse_name(record.data, 0)
                    oscquery_services[service_name] = {"name": service_name}
                except Exception:
                    continue

        # SRVレコードからポート情報を取得
        for record in records:
            if record.rtype == self.TYPE_SRV:
                service_name = record.name
                if service_name in oscquery_services:
                    try:
                        if len(record.data) >= 6:
                            priority, weight, port = struct.unpack(
                                "!HHH", record.data[:6]
                            )
                            oscquery_services[service_name]["port"] = port
                    except Exception:
                        continue

        # TXTレコードからOSCポート情報を取得
        for record in records:
            if record.rtype == self.TYPE_TXT:
                service_name = record.name
                if service_name in oscquery_services:
                    try:
                        txt_data = self._parse_txt_record(record.data)
                        if "osc-port" in txt_data:
                            oscquery_services[service_name]["osc_port"] = int(
                                txt_data["osc-port"]
                            )
                    except Exception:
                        continue

        # 完全な情報を持つサービスを通知
        for service_name, service_info in oscquery_services.items():
            if (
                "osc_port" in service_info
                and service_name not in self.discovered_services
            ):
                self.discovered_services[service_name] = service_info
                if self.service_callback:
                    callback_info = {
                        "ip_addresses": [src_ip],
                        "osc_port": service_info["osc_port"],
                    }
                    self.service_callback(callback_info)

    def _parse_txt_record(self, data: bytes) -> Dict[str, str]:
        # TXTレコードを解析
        result = {}
        offset = 0

        while offset < len(data):
            if offset >= len(data):
                break
            length = data[offset]
            if length == 0:
                break
            offset += 1

            if offset + length > len(data):
                break

            txt_string = data[offset : offset + length].decode("ascii", errors="ignore")
            if "=" in txt_string:
                key, value = txt_string.split("=", 1)
                result[key] = value

            offset += length

        return result


class OSCQueryServiceFinder:
    # OSCQueryサービス自動発見クラス
    def __init__(self, discovery_callback=None, log_callback=None):
        logger.debug("OSCQueryServiceFinder初期化")
        self.discovery_callback = discovery_callback
        self.log_callback = log_callback
        self.mdns_client = MDNSClient(self._on_service_discovered)
        self.query_timer = None

    # サービス発見を開始
    def start(self):
        try:
            self.mdns_client.start()
            self._start_periodic_query()
            if self.log_callback:
                self.log_callback("OSCQuery自動発見を開始 🔍", "osc")
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"OSCQuery発見開始エラー: {e}", "error")

    # サービス発見を停止
    def stop(self):
        if self.query_timer:
            self.query_timer.cancel()
        self.mdns_client.stop()

    # 定期的なクエリ送信を開始
    def _start_periodic_query(self):
        self.mdns_client.query_service("_oscjson._tcp.local.")
        self.query_timer = threading.Timer(5.0, self._start_periodic_query)
        self.query_timer.daemon = True
        self.query_timer.start()

    # サービス発見時のコールバック
    def _on_service_discovered(self, service_info):
        if self.log_callback:
            ip = (
                service_info["ip_addresses"][0]
                if service_info["ip_addresses"]
                else "N/A"
            )
            port = service_info.get("osc_port", "N/A")
            self.log_callback(f"OSCQuery発見: {ip}:{port} 🔍", "osc")

        if self.discovery_callback:
            self.discovery_callback(service_info)
