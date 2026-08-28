import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple

import librosa
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from core.constants import (
    BANDPASS_HZ,
    FRAME_LENGTH,
    HOP_LENGTH,
    PYIN_FMAX_HZ,
    PYIN_FMIN_HZ,
    SAMPLE_RATE,
)
from core.settings import RuleSettings, SnoreEvent

logger = logging.getLogger(__name__)


class FeatureExtractionError(RuntimeError):
    """特徴量抽出に失敗した（このチャンクはスキップする）"""


class FeatureExtractor:
    """音声チャンクからRMS、スペクトル重心、ZCR、F0を抽出"""

    def __init__(
        self,
        sample_rate: int,
        frame_length: int,
        hop_length: int,
        settings: RuleSettings,
    ):
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.hop_length = hop_length
        self.settings = settings

    def extract_features(self, audio_chunk: np.ndarray) -> Dict[str, np.ndarray]:
        """全特徴量を一括抽出。失敗時は FeatureExtractionError。

        すべての配列は同じフレーム数（1 + len(audio) // hop_length）で返る。
        旧実装の固定 20 フレームのフォールバックは形状不整合で検出スレッドを
        落としていたため廃止した。
        """
        try:
            f0, _voiced_flag, voiced_probs = librosa.pyin(
                y=audio_chunk,
                fmin=PYIN_FMIN_HZ,
                fmax=PYIN_FMAX_HZ,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )
            return {
                "rms": librosa.feature.rms(
                    y=audio_chunk,
                    frame_length=self.frame_length,
                    hop_length=self.hop_length,
                )[0],
                "spectral_centroid": librosa.feature.spectral_centroid(
                    y=audio_chunk,
                    sr=self.sample_rate,
                    n_fft=self.frame_length,
                    hop_length=self.hop_length,
                )[0],
                "zcr": librosa.feature.zero_crossing_rate(
                    y=audio_chunk,
                    frame_length=self.frame_length,
                    hop_length=self.hop_length,
                )[0],
                "f0": np.nan_to_num(f0, nan=0.0),
                "voiced_probs": voiced_probs,
            }
        except Exception as e:
            raise FeatureExtractionError(str(e)) from e


class MaskProcessor:
    """マスク処理クラス"""

    def __init__(self, max_frames: int, settings: RuleSettings):
        self.max_frames = max_frames
        self.settings = settings
        self._init_temp_arrays()

    def _init_temp_arrays(self):
        """一時配列を初期化"""
        self._temp_arrays = {
            "energy_mask": np.zeros(self.max_frames, dtype=bool),
            "f0_conf_mask": np.zeros(self.max_frames, dtype=bool),
            "f0_range_mask": np.zeros(self.max_frames, dtype=bool),
            "centroid_mask": np.zeros(self.max_frames, dtype=bool),
            "zcr_mask": np.zeros(self.max_frames, dtype=bool),
        }

    def create_masks(
        self, features: Dict[str, np.ndarray]
    ) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
        """特徴量からマスクを作成"""
        num_frames = len(features["rms"])
        num_frames = min(num_frames, self.max_frames)

        # 各マスクを作成
        self._temp_arrays["energy_mask"][:num_frames] = (
            features["rms"][:num_frames] > self.settings.energy_threshold
        )
        self._temp_arrays["f0_conf_mask"][:num_frames] = (
            features["voiced_probs"][:num_frames]
            > self.settings.f0_confidence_threshold
        )

        f0_valid = np.logical_and(
            features["f0"][:num_frames] > 0,
            np.logical_and(
                features["f0"][:num_frames] >= self.settings.f0_min_hz,
                features["f0"][:num_frames] <= self.settings.f0_max_hz,
            ),
        )
        self._temp_arrays["f0_range_mask"][:num_frames] = f0_valid

        self._temp_arrays["centroid_mask"][:num_frames] = (
            features["spectral_centroid"][:num_frames]
            < self.settings.spectral_centroid_threshold
        )
        self._temp_arrays["zcr_mask"][:num_frames] = (
            features["zcr"][:num_frames] < self.settings.zcr_threshold
        )

        # 最終マスクを作成
        final_mask = np.logical_and.reduce(
            [
                self._temp_arrays["energy_mask"][:num_frames],
                self._temp_arrays["f0_conf_mask"][:num_frames],
                self._temp_arrays["f0_range_mask"][:num_frames],
                self._temp_arrays["centroid_mask"][:num_frames],
                self._temp_arrays["zcr_mask"][:num_frames],
            ]
        )

        pass_masks = {
            "energy": self._temp_arrays["energy_mask"][:num_frames],
            "f0_confidence": self._temp_arrays["f0_conf_mask"][:num_frames],
            "f0_range": self._temp_arrays["f0_range_mask"][:num_frames],
            "spectral_centroid": self._temp_arrays["centroid_mask"][:num_frames],
            "zcr": self._temp_arrays["zcr_mask"][:num_frames],
        }

        return pass_masks, final_mask


class SegmentProcessor:
    """final_mask の連続 True 区間をいびき候補イベントにする。

    1 秒チャンクごとに呼ばれるが、チャンク末尾まで True の区間は「開いたまま」
    次のチャンクへ持ち越す。これにより max_duration（長すぎる連続音の棄却）が
    本来の意味で機能し、境界で分断された 1 回のいびきも 1 イベントになる。
    """

    def __init__(self, hop_length: int, sample_rate: int, settings: RuleSettings):
        self.hop_length = hop_length
        self.sample_rate = sample_rate
        self.settings = settings
        self.frame_seconds = hop_length / sample_rate
        self.reset()

    def reset(self):
        """持ち越し中のセグメントを破棄"""
        self._open_frames = 0
        self._open_start: datetime | None = None
        self._open_rms: list[float] = []
        self._open_f0: list[float] = []
        self._open_too_long = False

    def process_segments(
        self,
        final_mask: np.ndarray,
        features: Dict[str, np.ndarray],
        chunk_start: datetime,
    ) -> list:
        """チャンク内のマスクを走査し、閉じたセグメントからイベントを作る"""
        events = []
        n = len(final_mask)
        i = 0

        if self._open_frames > 0:
            # 前チャンクから継続中のセグメント
            j = 0
            while j < n and final_mask[j]:
                j += 1
            self._extend_open(features, 0, j)
            if j >= n:
                return events  # まだ閉じていない
            event = self._close_open()
            if event:
                events.append(event)
            i = j

        while i < n:
            if not final_mask[i]:
                i += 1
                continue
            j = i
            while j < n and final_mask[j]:
                j += 1
            self._open_start = chunk_start + timedelta(seconds=i * self.frame_seconds)
            self._extend_open(features, i, j)
            if j >= n:
                break  # チャンク末尾まで True → 持ち越し
            event = self._close_open()
            if event:
                events.append(event)
            i = j

        return events

    def _extend_open(self, features: Dict[str, np.ndarray], start: int, end: int):
        """開いているセグメントにフレーム [start, end) を追加"""
        count = end - start
        if count <= 0:
            return
        self._open_frames += count
        if self._open_frames * self.frame_seconds > self.settings.max_duration_seconds:
            # 長すぎる連続音: 以降の統計は捨て、閉じたときに棄却する
            self._open_too_long = True
            self._open_rms.clear()
            self._open_f0.clear()
            return
        self._open_rms.extend(float(v) for v in features["rms"][start:end])
        self._open_f0.extend(float(v) for v in features["f0"][start:end])

    def _close_open(self) -> SnoreEvent | None:
        """開いているセグメントを閉じ、持続時間が範囲内ならイベントを返す"""
        duration = self._open_frames * self.frame_seconds
        start = self._open_start
        rms_values = np.array(self._open_rms, dtype=np.float32)
        f0_values = np.array(self._open_f0, dtype=np.float32)
        too_long = self._open_too_long
        self.reset()

        if too_long or start is None:
            return None
        if not (
            self.settings.min_duration_seconds
            <= duration
            <= self.settings.max_duration_seconds
        ):
            return None
        valid_f0 = f0_values[f0_values > 0]
        return SnoreEvent(
            timestamp=start,
            duration=duration,
            f0=float(np.mean(valid_f0)) if len(valid_f0) else 0.0,
            energy=float(np.mean(rms_values)) if len(rms_values) else 0.0,
        )


class RuleBasedProcessor:
    """ルールベースのイベント検知クラス"""

    def __init__(
        self,
        settings: RuleSettings,
        callback: Callable[[], None],
        clock: Callable[[], datetime] = datetime.now,
    ):
        self.settings = settings
        self.on_snore_detected = callback

        # 音声処理パラメータ
        self.sample_rate = SAMPLE_RATE
        self.frame_length = FRAME_LENGTH
        self.hop_length = HOP_LENGTH
        self.max_frames = int(self.sample_rate * 5.0 / self.hop_length)

        # イベント管理
        self.recent_events: deque = deque(maxlen=20)

        # フィルター
        self.sos_filter = butter(
            N=5,
            Wn=list(BANDPASS_HZ),
            btype="bandpass",
            fs=self.sample_rate,
            output="sos",
        )
        self.clock = clock
        # 帯域通過フィルタの内部状態 (n_sections, 2)
        self._zi = sosfilt_zi(self.sos_filter) * 0.0

        # コンポーネント初期化
        self.feature_extractor = FeatureExtractor(
            self.sample_rate, self.frame_length, self.hop_length, self.settings
        )
        self.mask_processor = MaskProcessor(self.max_frames, self.settings)
        self.segment_processor = SegmentProcessor(
            self.hop_length, self.sample_rate, self.settings
        )

        self._warmup_librosa()
        logger.debug("RuleBasedProcessor 初期化完了")

    def _warmup_librosa(self):
        """librosa機能のプリコンパイル"""
        try:
            logger.debug("librosa機能をプリコンパイル中...")
            dummy_audio = np.random.random(self.sample_rate // 10).astype(np.float32)
            self.feature_extractor.extract_features(dummy_audio)
            logger.debug("librosaプリコンパイル完了")
        except Exception as e:
            logger.error(f"librosaプリコンパイル中にエラー: {e}")

    def reset_periodicity(self):
        """周期性イベントキュー・持ち越しセグメント・フィルタ状態をリセット"""
        self.recent_events.clear()
        self.segment_processor.reset()
        self._zi[...] = 0.0
        logger.debug("周期性イベントキューがリセットされました。")

    def process_audio_chunk(
        self, audio_chunk: np.ndarray, chunk_start: datetime | None = None
    ) -> Dict[str, Any]:
        """音声チャンクの処理。特徴量抽出に失敗したチャンクは {} を返してスキップ"""
        if chunk_start is None:
            chunk_start = self.clock() - timedelta(
                seconds=len(audio_chunk) / self.sample_rate
            )

        filtered_chunk, self._zi = sosfilt(self.sos_filter, audio_chunk, zi=self._zi)

        try:
            features = self.feature_extractor.extract_features(filtered_chunk)
        except FeatureExtractionError as e:
            logger.warning(f"特徴量抽出に失敗したためチャンクをスキップ: {e}")
            return {}

        features = self._limit_frame_count(features)
        pass_masks, final_mask = self.mask_processor.create_masks(features)

        events = self.segment_processor.process_segments(
            final_mask, features, chunk_start
        )
        for event in events:
            self.register_event(event)

        return {
            "analysis_results": features,
            "pass_masks": {k: v.copy() for k, v in pass_masks.items()},
            "final_mask_frames": final_mask,
            "recent_events_count": len(self.recent_events),
            "first_event_timestamp": self.recent_events[0].timestamp
            if self.recent_events
            else None,
        }

    def register_event(self, event: SnoreEvent) -> None:
        """イベントを周期列に登録し、間隔条件と周期性条件を評価する"""
        s = self.settings
        if self.recent_events:
            gap = (event.timestamp - self.recent_events[-1].timestamp).total_seconds()
            if gap < s.min_event_interval_seconds:
                logger.debug(
                    f"イベント間隔 {gap:.2f}s が短すぎるため同一イベントとして無視"
                )
                return
            if gap > s.max_event_interval_seconds:
                logger.debug(f"イベント間隔 {gap:.2f}s が長すぎるため周期列をリセット")
                self.recent_events.clear()
        self.recent_events.append(event)
        self._check_periodicity(event.timestamp)

    def _limit_frame_count(
        self, features: Dict[str, np.ndarray]
    ) -> Dict[str, np.ndarray]:
        """フレーム数を制限"""
        num_frames = len(features["rms"])
        if num_frames > self.max_frames:
            logger.warning(
                f"フレーム数が最大値を超過 ({num_frames} > {self.max_frames})"
            )
            for key in features:
                features[key] = features[key][: self.max_frames]
        return features

    def _check_periodicity(self, now: datetime):
        """周期ウィンドウ内のイベント数が閾値に達したら検出コールバックを呼ぶ"""
        window_start = now - timedelta(seconds=self.settings.periodicity_window_seconds)
        while self.recent_events and self.recent_events[0].timestamp < window_start:
            self.recent_events.popleft()
        if len(self.recent_events) >= self.settings.periodicity_event_count:
            logger.info(
                f"いびき検知成功！周期ウィンドウ内に{len(self.recent_events)}回のイベントを検出"
            )
            self.on_snore_detected()
            self.recent_events.clear()
