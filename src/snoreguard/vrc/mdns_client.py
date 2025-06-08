import logging
import socket
import struct
import threading
import time
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class MDNSRecord:
    """
    mDNSレコードを表現するデータクラス
    - DNSレコードの基本情報（名前、タイプ、クラス、TTL、データ）を保持
    """

    def __init__(self, name: str, rtype: int, rclass: int, ttl: int, data: bytes):
        """
        mDNSレコードを初期化
        - name: ドメイン名
        - rtype: レコードタイプ（A、PTR、TXT、SRVなど）
        - rclass: レコードクラス
        - ttl: 生存時間（秒）
        - data: レコードデータ（バイナリ）
        """
        self.name = name
        self.rtype = rtype
        self.rclass = rclass
        self.ttl = ttl
        self.data = data


class MDNSClient:
    """
    mDNS（Multicast DNS）プロトコルのクライアント実装
    - ローカルネットワーク上のサービスを探索し、VRChatのOSCQueryサービスを
    - 自動的に発見するために使用。RFC 6762のmDNS仕様に基づく
    """

    # mDNSプロトコルの標準設定
    MDNS_PORT = 5353  # mDNS標準ポート
    MDNS_GROUP = "224.0.0.251"  # IPv4 mDNSマルチキャストアドレス

    # DNSレコードタイプ定数（RFC 1035）
    TYPE_A = 1  # IPv4アドレスレコード
    TYPE_PTR = 12  # ポインターレコード（サービス探索用）
    TYPE_TXT = 16  # テキストレコード（サービスメタデータ）
    TYPE_SRV = 33  # サービスレコード（ホストとポート情報）

    def __init__(self, service_callback: Optional[Callable] = None):
        """
        mDNSクライアントを初期化
        - service_callback: サービス発見時のコールバック関数
        """
        logger.debug("MDNSClient初期化")
        self.socket = None
        self.running = False
        self.thread = None
        self.service_callback = service_callback
        self.discovered_services: Dict[str, Dict] = {}  # 発見したサービスのキャッシュ

    def start(self):
        """
        mDNSマルチキャスト受信を開始
        - UDPソケットを作成し、mDNSマルチキャストグループに参加
        - 別スレッドで受信ループを開始し、ネットワーク上のサービス広告を監視
        """
        logger.debug("mDNSクライアント開始")
        if self.running:
            logger.debug("mDNSクライアント既に実行中")
            return

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # ポート再利用設定（Windowsでは未サポートのため条件付き）
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # Windowsではスキップ

            self.socket.bind(("", self.MDNS_PORT))

            # IPv4 mDNSマルチキャストグループに参加
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

    def stop(self):
        """
        mDNS受信を停止し、リソースをクリーンアップ
        - マルチキャストグループから脱退し、ソケットを閉じ、スレッドの終了を待機
        """
        logger.debug("mDNSクライアント停止")
        self.running = False
        if self.socket:
            try:
                # マルチキャストグループから正常に脱退
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

    def query_service(self, service_type: str):
        """
        指定されたサービスタイプのmDNSクエリを送信
        - service_type: 検索するサービスタイプ（例：_oscjson._tcp.local.）
        """
        if not self.socket:
            return

        try:
            query = self._build_query(service_type)
            self.socket.sendto(query, (self.MDNS_GROUP, self.MDNS_PORT))
        except Exception:
            pass  # クエリ送信エラーは無視

    def _listen_loop(self):
        """
        mDNSパケットの連続受信ループ（別スレッドで実行）
        - マルチキャストグループからパケットを受信し、
        - パースしてサービス情報
        """
        while self.running:
            try:
                data, addr = self.socket.recvfrom(4096)
                self._parse_mdns_response(data, addr[0])
            except socket.timeout:
                continue
            except Exception:
                if self.running:
                    time.sleep(0.1)

    def _build_query(self, service_type: str) -> bytes:
        """mDNSクエリパケットを構築"""
        # DNS Header
        header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)  # ID=0, QR=0, OPCODE=0, etc.

        # Question Section
        question = self._encode_name(service_type)
        question += struct.pack("!HH", self.TYPE_PTR, 1)  # TYPE=PTR, CLASS=IN

        return header + question

    def _encode_name(self, name: str) -> bytes:
        """DNS名前形式にエンコード"""
        result = b""
        for part in name.split("."):
            if part:
                result += struct.pack("!B", len(part)) + part.encode("ascii")
        result += b"\x00"  # 終端
        return result

    def _parse_mdns_response(self, data: bytes, src_ip: str):
        """mDNS応答パケットを解析"""
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

    def _parse_name(self, data: bytes, offset: int) -> tuple[str, int]:
        """DNS名前を解析"""
        parts = []
        original_offset = offset
        jumped = False

        # 名前を解析
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

    def _parse_resource_record(
        self, data: bytes, offset: int
    ) -> tuple[Optional[MDNSRecord], int]:
        """リソースレコードを解析"""
        try:
            name, offset = self._parse_name(data, offset)

            if offset + 10 > len(data):
                # レコードデータの長さを超えている場合は無視
                return None, offset

            rtype, rclass, ttl, rdlen = struct.unpack(
                "!HHIH", data[offset : offset + 10]
            )
            offset += 10

            if offset + rdlen > len(data):
                # レコードデータの長さを超えている場合は無視
                return None, offset

            rdata = data[offset : offset + rdlen]
            offset += rdlen

            return MDNSRecord(name, rtype, rclass, ttl, rdata), offset

        except Exception:
            return None, offset

    def _process_service_records(self, records: List[MDNSRecord], src_ip: str):
        """
        受信したmDNSレコードからOSCQueryサービスを特定して抽出する。
        - PTRレコードからサービス名、SRVレコードからポート、
        - TXTレコードからOSCポートを取得し、完全なサービス情報を組み立てる。
        - records: 処理対象のmDNSレコードリスト
        - src_ip: レコードの送信元IPアドレス
        """
        oscquery_services = {}

        # 段階1: PTRレコードからOSCQueryサービスのインスタンス名を収集
        for record in records:
            if record.rtype == self.TYPE_PTR and "_oscjson._tcp.local" in record.name:
                try:
                    service_name, _ = self._parse_name(record.data, 0)
                    oscquery_services[service_name] = {"name": service_name}
                except Exception:
                    continue  # パースエラーは無視

        # 段階2: SRVレコードからサービスのホストとポート情報を収集
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

        # 段階3: TXTレコードからOSCポートなどのメタデータを収集
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

        # 段階4: 必要な情報が揃ったサービスをコールバックで通知
        for service_name, service_info in oscquery_services.items():
            if (
                "osc_port" in service_info  # OSCポート情報が必須
                and service_name not in self.discovered_services  # 新規発見のみ
            ):
                self.discovered_services[service_name] = service_info
                if self.service_callback:
                    callback_info = {
                        "ip_addresses": [src_ip],
                        "osc_port": service_info["osc_port"],
                    }
                    self.service_callback(callback_info)

    def _parse_txt_record(self, data: bytes) -> Dict[str, str]:
        """TXTレコードを解析"""
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

            # TXTレコードを解析
            txt_string = data[offset : offset + length].decode("ascii", errors="ignore")
            if "=" in txt_string:
                key, value = txt_string.split("=", 1)
                result[key] = value

            # 次のTXTレコードの位置に移動
            offset += length

        return result


class OSCQueryServiceFinder:
    """
    OSCQueryサービスの自動発見を行うメインクラス。
    - mDNSクライアントを使用してVRChatのOSCQueryサービスを探索し、
    - 定期的なクエリ送信でサービスの可用性を監視する。
    """

    def __init__(self, discovery_callback=None, log_callback=None):
        """
        OSCQueryServiceFinderを初期化
        - discovery_callback: サービス発見時のコールバック関数
        - log_callback: ログ出力用コールバック関数
        """
        logger.debug("OSCQueryServiceFinder初期化")
        self.discovery_callback = discovery_callback
        self.log_callback = log_callback
        self.mdns_client = MDNSClient(self._on_service_discovered)
        self.query_timer = None  # 定期クエリ用タイマー

    def start(self):
        """
        OSCQueryサービスの自動発見を開始
        - mDNSクライアントを起動し、定期的なサービスクエリを開始
        """
        try:
            self.mdns_client.start()  # mDNSクライアントを開始
            self._start_periodic_query()  # 定期的なクエリ送信を開始
            if self.log_callback:
                self.log_callback("OSCQuery自動発見を開始", "osc")
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"OSCQuery発見開始エラー: {e}", "error")

    def stop(self):
        """
        OSCQueryサービスの自動発見を停止
        - 定期タイマーをキャンセルし、mDNSクライアントを停止
        """
        if self.query_timer:
            self.query_timer.cancel()
        self.mdns_client.stop()  # mDNSクライアントを停止

    def _start_periodic_query(self):
        """
        OSCQueryサービスの定期クエリを開始
        - 5秒間隔で_oscjson._tcp.local.サービスへのクエリを送信
        - 再帰的にタイマーを設定して継続的に実行
        """
        # OSCQueryサービスタイプへのクエリを送信
        self.mdns_client.query_service("_oscjson._tcp.local.")

        # 5秒後の次回クエリをスケジュール
        self.query_timer = threading.Timer(5.0, self._start_periodic_query)
        self.query_timer.daemon = True  # メインスレッド終了時に自動終了
        self.query_timer.start()

    def _on_service_discovered(self, service_info):
        """
        mDNSでサービスが発見された時の内部コールバック
        - 発見したサービス情報をログ出力し、上位のコールバックへ通知
        - service_info: 発見したサービスの情報
        """
        if self.log_callback:
            ip = (
                service_info["ip_addresses"][0]
                if service_info["ip_addresses"]
                else "N/A"
            )
            port = service_info.get("osc_port", "N/A")
            self.log_callback(f"OSCQuery発見: {ip}:{port}", "osc")

        # 上位レイヤーのコールバックにサービス情報を渡す
        if self.discovery_callback:
            self.discovery_callback(service_info)
