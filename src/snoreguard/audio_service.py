import logging
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd
from core.rule_processor import RuleBasedProcessor

logger = logging.getLogger(__name__)


class AudioService:
    """
    音声処理、いびき検出、スレッド管理を担当
    - オーディオストリームの管理
    - ルールベースプロセッサの管理
    - スレッド管理
    """

    SAMPLE_RATE = 16000  # サンプリングレート
    VIZ_CHUNK_SIZE = 800  # 0.05秒
    ANALYSIS_CHUNK_DURATION_S = 1.0  # 分析チャンクの長さ
    N_FFT = 800  # FFTのサイズ

    _spectrum_buffer: np.ndarray | None = None  # スペクトラムバッファ
    _fft_buffer: np.ndarray | None = None  # FFTバッファ

    def __init__(
        self,
        rule_settings,
        data_queue,
        snore_detected_callback: Callable[[], None],
        log_callback: Callable[[str, str], None],
    ):
        logger.debug("AudioService初期化開始")
        self.rule_settings = rule_settings  # ルール設定
        self.data_queue = data_queue  # データキュー
        self.snore_detected_callback = snore_detected_callback  # いびき検出コールバック
        self.log_callback = log_callback  # ログコールバック

        self.processor = RuleBasedProcessor(
            self.rule_settings, self.snore_detected_callback
        )  # ルールベースプロセッサ
        self.is_running = False  # 実行中フラグ
        self._thread: threading.Thread | None = None  # スレッド
        self.stream: sd.InputStream | None = None  # ストリーム

        # バッファの事前割り当て
        max_buffer_size = int(self.SAMPLE_RATE * self.ANALYSIS_CHUNK_DURATION_S * 2)
        self.analysis_buffer = np.zeros(
            max_buffer_size, dtype=np.float32
        )  # 分析バッファ
        self._buffer_size = 0  # バッファサイズ

        # FFT関連バッファの事前割り当て
        self._spectrum_buffer = np.zeros(
            self.N_FFT // 2 + 1, dtype=np.float32
        )  # スペクトラムバッファ
        self._fft_buffer = np.zeros(self.N_FFT, dtype=np.float64)  # FFTバッファ

        logger.debug(
            f"AudioService初期化完了 - SR:{self.SAMPLE_RATE}, FFT:{self.N_FFT}"
        )

    def start(self, device_id: int):
        """検出スレッドを開始"""
        logger.debug(f"AudioService開始要求 - device_id: {device_id}")
        if self.is_running:
            logger.warning("AudioService既に実行中")
            return

        # デバイスの有効性を確認
        try:
            devices = sd.query_devices()
            if device_id >= len(devices):
                raise ValueError(f"無効なデバイスID: {device_id}")

            device_info = devices[device_id]
            if device_info.get("max_input_channels", 0) <= 0:
                raise ValueError(
                    f"入力チャンネルがないデバイス: {device_info.get('name', 'Unknown')}"
                )

            logger.debug(f"デバイス検証完了: {device_info.get('name', 'Unknown')}")

        except Exception as e:
            logger.error(f"デバイス検証失敗: {e}")
            raise

        self.is_running = True  # 実行中フラグをセット
        self._buffer_size = 0  # バッファサイズをリセット
        logger.debug("検出スレッド作成中")

        self._thread = threading.Thread(
            target=self._detection_loop, args=(device_id,), daemon=True
        )
        self._thread.start()
        logger.info(f"AudioService開始完了 - device_id: {device_id}")

    def stop(self):
        """検出スレッドを停止"""
        logger.debug("AudioService停止要求")
        self.is_running = False  # 実行中フラグをクリア

        # スレッドが存在する場合
        if self._thread and self._thread.is_alive():
            logger.debug("検出スレッド終了待機中")
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                logger.warning("検出スレッドが正常に終了しませんでした")
        self._thread = None
        self._buffer_size = 0  # バッファサイズをリセット
        logger.info("AudioService停止完了")

    def reset_processor_periodicity(self):
        """プロセッサの周期性イベントをリセット"""
        self.processor.reset_periodicity()

    def _detection_loop(self, device_id: int):
        """音声入力と処理のメインループを開始"""
        logger.debug(f"検出ループ開始 - device_id: {device_id}")
        try:
            # オーディオストリームを開始
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                device=device_id,
                channels=1,
                dtype="float32",
                blocksize=self.VIZ_CHUNK_SIZE,
            ) as self.stream:
                logger.info(
                    f"オーディオストリーム開始 - device: {device_id}, SR: {self.SAMPLE_RATE}"
                )
                self.log_callback("オーディオストリームを開始しました。", "system")

                # 実行中フラグがTrueの間ループ
                while self.is_running:
                    self._process_stream_data()

        except Exception as e:
            if self.is_running:
                logger.error(f"検出ループでエラー発生: {e}", exc_info=True)
                self.log_callback(
                    f"検出ループで致命的なエラーが発生しました: {e}", "error"
                )
        finally:
            logger.info("検出ループ終了")
            self.log_callback("オーディオストリームを停止しました。", "system")
            self.is_running = False  # 実行中フラグをクリア

    def _process_stream_data(self):
        """ストリームからデータを読み込み、処理キューに追加"""
        # 実行中フラグがFalseまたはストリームがNoneの場合
        if not self.is_running or not self.stream:
            return

        # ストリームからデータを読み込み
        viz_chunk, overflowed = self.stream.read(self.VIZ_CHUNK_SIZE)
        if overflowed:
            logger.warning("オーディオバッファオーバーフロー")
            self.log_callback("オーディオバッファがオーバーフローしました。", "warning")

        # データを平坦化
        flat_chunk = viz_chunk.flatten()

        # 可視化用データのキューイング
        spectrum = self._calculate_spectrum_optimized(flat_chunk)
        if not self.data_queue.full():
            self.data_queue.put(("viz", flat_chunk, spectrum))

        # 分析用データの処理（最適化版）
        analysis_chunk_size = int(self.SAMPLE_RATE * self.ANALYSIS_CHUNK_DURATION_S)

        # バッファオーバーフロー防止
        if self._buffer_size + len(flat_chunk) > len(self.analysis_buffer):
            # バッファが満杯の場合、古いデータを削除
            shift_size = self._buffer_size + len(flat_chunk) - len(self.analysis_buffer)
            self.analysis_buffer[:-shift_size] = self.analysis_buffer[shift_size:]
            self._buffer_size -= shift_size

        # 新しいデータを追加
        end_idx = self._buffer_size + len(flat_chunk)
        self.analysis_buffer[self._buffer_size : end_idx] = flat_chunk
        self._buffer_size = end_idx

        # バッファが分析チャンクサイズ以上になった場合
        if self._buffer_size >= analysis_chunk_size:
            analysis_chunk = self.analysis_buffer[:analysis_chunk_size]
            logger.debug(f"音声分析実行 - chunk_size: {len(analysis_chunk)}")
            analysis_result_dict = self.processor.process_audio_chunk(analysis_chunk)
            if analysis_result_dict and not self.data_queue.full():
                self.data_queue.put(("analysis", analysis_result_dict))
                logger.debug("分析結果をキューに追加")
            elif self.data_queue.full():
                logger.debug("データキューが満杯")

            # バッファから処理済みデータを削除
            remaining_size = self._buffer_size - analysis_chunk_size
            if remaining_size > 0:
                self.analysis_buffer[:remaining_size] = self.analysis_buffer[
                    analysis_chunk_size : self._buffer_size
                ]
            self._buffer_size = remaining_size

    def _calculate_spectrum_optimized(self, chunk: np.ndarray) -> np.ndarray:
        """最適化されたFFT計算（事前割り当てバッファ使用）"""
        chunk_len = len(chunk)
        logger.debug(f"スペクトラム計算 - chunk_len: {chunk_len}")
        chunk_float64 = chunk.astype(np.float64)

        if chunk_len <= self.N_FFT:
            self._fft_buffer[:chunk_len] = chunk_float64
            if chunk_len < self.N_FFT:
                self._fft_buffer[chunk_len:] = 0
        else:
            # チャンクが大きすぎる場合は切り詰める
            self._fft_buffer[:] = chunk_float64[: self.N_FFT]

        # FFT計算
        fft_result = np.fft.rfft(self._fft_buffer.astype(np.float64))

        # 絶対値を計算
        spectrum = np.abs(fft_result) / self.N_FFT

        return spectrum.astype(np.float32)  # メモリ効率のためfloat32で返す
