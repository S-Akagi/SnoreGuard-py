import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple

import librosa
import numpy as np
from scipy.signal import butter, sosfilt

from core.settings import RuleSettings, SnoreEvent

logger = logging.getLogger(__name__)


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
        """全特徴量を一括抽出"""
        features = {
            "rms": self._extract_rms(audio_chunk),
            "spectral_centroid": self._extract_spectral_centroid(audio_chunk),
            "zcr": self._extract_zcr(audio_chunk),
        }
        features.update(self._extract_f0(audio_chunk))
        return features

    def _extract_rms(self, audio_chunk: np.ndarray) -> np.ndarray:
        """RMSエネルギーを抽出（音量の指標）"""
        try:
            return librosa.feature.rms(
                y=audio_chunk,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
        except Exception as e:
            logger.error(f"RMS抽出エラー: {e}")
            return self._fallback_rms(audio_chunk)  # 手動計算でフォールバック

    def _extract_spectral_centroid(self, audio_chunk: np.ndarray) -> np.ndarray:
        """スペクトル重心を抽出（音色の指標）"""
        try:
            return librosa.feature.spectral_centroid(
                y=audio_chunk,
                sr=self.sample_rate,
                n_fft=self.frame_length,
                hop_length=self.hop_length,
            )[0]
        except Exception as e:
            logger.error(f"スペクトル重心抽出エラー: {e}")
            return self._fallback_spectral_centroid()

    def _extract_zcr(self, audio_chunk: np.ndarray) -> np.ndarray:
        """ゼロ交差率を抽出（有声/無声の指標）"""
        try:
            return librosa.feature.zero_crossing_rate(
                y=audio_chunk,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
        except Exception as e:
            logger.error(f"ゼロ交差率抽出エラー: {e}")
            return self._fallback_zcr()

    def _extract_f0(self, audio_chunk: np.ndarray) -> Dict[str, np.ndarray]:
        """基本周波数（音の高さ）と有声確率を抽出"""
        try:
            f0, voiced_flag, voiced_probs = librosa.pyin(
                y=audio_chunk,
                fmin=self.settings.f0_min_hz,
                fmax=self.settings.f0_max_hz,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )
            return {"f0": np.nan_to_num(f0, nan=0.0), "voiced_probs": voiced_probs}
        except Exception as e:
            logger.error(f"F0抽出エラー: {e}")
            return self._fallback_f0()

    def _fallback_rms(self, audio_chunk: np.ndarray) -> np.ndarray:
        """RMSの手動計算（librosa失敗時）"""
        hop_samples = len(audio_chunk) // 20  # 20フレームに分割
        rms_values = []
        for i in range(0, len(audio_chunk), hop_samples):
            window = audio_chunk[i : i + hop_samples]
            if len(window) > 0:
                rms_values.append(np.sqrt(np.mean(window**2)))  # RMS = 二乗平均平方根
        return np.array(rms_values, dtype=np.float32)

    def _fallback_spectral_centroid(self) -> np.ndarray:
        """スペクトル重心のフォールバック値"""
        return np.full(20, self.sample_rate / 4, dtype=np.float32)

    def _fallback_zcr(self) -> np.ndarray:
        """ゼロ交差率のフォールバック値"""
        return np.full(20, 0.1, dtype=np.float32)

    def _fallback_f0(self) -> Dict[str, np.ndarray]:
        """F0のフォールバック値"""
        return {
            "f0": np.zeros(20, dtype=np.float32),
            "voiced_probs": np.zeros(20, dtype=np.float32),
        }


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
    """セグメント処理クラス"""

    def __init__(self, hop_length: int, sample_rate: int, settings: RuleSettings):
        self.hop_length = hop_length
        self.sample_rate = sample_rate
        self.settings = settings
        self.candidate_frames_info = []

    def process_segments(
        self, final_mask: np.ndarray, features: Dict[str, np.ndarray]
    ) -> list:
        """セグメントを処理してイベント候補を抽出"""
        mask_changes = np.diff(
            np.concatenate(([False], final_mask, [False])).astype(int)
        )
        starts = np.where(mask_changes == 1)[0]
        ends = np.where(mask_changes == -1)[0]

        events = []
        for start, end in zip(starts, ends):
            if end > start:
                segment_data = [
                    {"rms": features["rms"][i], "f0": features["f0"][i]}
                    for i in range(start, end)
                ]
                event = self._create_event_from_segment(segment_data)
                if event:
                    events.append(event)

        return events

    def _create_event_from_segment(self, segment_data: list) -> SnoreEvent | None:
        """セグメントデータからイベントを作成"""
        if not segment_data:
            return None

        event_duration = len(segment_data) * self.hop_length / self.sample_rate

        if not (
            self.settings.min_duration_seconds
            <= event_duration
            <= self.settings.max_duration_seconds
        ):
            return None

        rms_values = np.array([data["rms"] for data in segment_data], dtype=np.float32)
        f0_values = np.array([data["f0"] for data in segment_data], dtype=np.float32)

        avg_energy = float(np.mean(rms_values))
        valid_f0s = f0_values[f0_values > 0]
        avg_f0 = float(np.mean(valid_f0s)) if len(valid_f0s) > 0 else 0.0

        return SnoreEvent(
            timestamp=datetime.now(),
            duration=event_duration,
            f0=avg_f0,
            energy=avg_energy,
        )


class RuleBasedProcessor:
    """ルールベースのイベント検知クラス"""

    def __init__(self, settings: RuleSettings, callback: Callable[[], None]):
        self.settings = settings
        self.on_snore_detected = callback

        # 音声処理パラメータ
        self.sample_rate = 16000
        self.frame_length = 480
        self.hop_length = 240
        self.max_frames = int(self.sample_rate * 5.0 / self.hop_length)

        # イベント管理
        self.recent_events: deque = deque(maxlen=20)

        # フィルター
        self.sos_filter = butter(
            N=5, Wn=[80, 1600], btype="bandpass", fs=self.sample_rate, output="sos"
        )

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
        """周期性イベントキューのリセット"""
        self.recent_events.clear()
        logger.debug("周期性イベントキューがリセットされました。")

    def process_audio_chunk(self, audio_chunk: np.ndarray) -> Dict[str, Any]:
        """音声チャンクの処理"""
        filtered_chunk = sosfilt(self.sos_filter, audio_chunk, axis=0)

        # 特徴量抽出
        features = self.feature_extractor.extract_features(filtered_chunk)
        if not features:
            return {}

        # フレーム数制限
        features = self._limit_frame_count(features)

        # マスク作成
        pass_masks, final_mask = self.mask_processor.create_masks(features)

        # セグメント処理
        events = self.segment_processor.process_segments(final_mask, features)
        for event in events:
            self.recent_events.append(event)
            self._check_periodicity()

        # 統計計算
        self._calculate_detailed_stats(features, pass_masks)

        return {
            "analysis_results": features,
            "pass_masks": pass_masks,
            "final_mask_frames": final_mask,
            "recent_events_count": len(self.recent_events),
            "first_event_timestamp": self.recent_events[0].timestamp
            if self.recent_events
            else None,
        }

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

    def _check_periodicity(self):
        """周期性のチェック"""
        now = datetime.now()
        window_start_time = now - timedelta(
            seconds=self.settings.periodicity_window_seconds
        )

        # 古いイベントを削除
        while (
            self.recent_events and self.recent_events[0].timestamp < window_start_time
        ):
            self.recent_events.popleft()

        # 周期性チェック
        if len(self.recent_events) >= self.settings.periodicity_event_count:
            logger.info(
                f"いびき検知成功！周期ウィンドウ内に{len(self.recent_events)}回のイベントを検出"
            )
            self.on_snore_detected()
            self.recent_events.clear()

    def _calculate_detailed_stats(
        self, features: Dict[str, np.ndarray], pass_masks: Dict[str, np.ndarray]
    ) -> Dict[str, float]:
        """詳細な統計を計算"""
        stats = {}

        # 特徴量の統計
        for key, values in features.items():
            if values is not None and len(values) > 0:
                try:
                    valid_values = (
                        values[~np.isnan(values)]
                        if hasattr(values, "dtype")
                        and np.issubdtype(values.dtype, np.floating)
                        else values
                    )
                    if len(valid_values) > 0:
                        stats[f"{key}_avg"] = float(np.mean(valid_values))
                        stats[f"{key}_max"] = float(np.max(valid_values))
                        stats[f"{key}_min"] = float(np.min(valid_values))
                    else:
                        stats[f"{key}_avg"] = stats[f"{key}_max"] = stats[
                            f"{key}_min"
                        ] = 0.0
                except Exception as e:
                    logger.error(f"統計計算エラー ({key}): {e}")
                    stats[f"{key}_avg"] = stats[f"{key}_max"] = stats[f"{key}_min"] = (
                        0.0
                    )

        # マスクの統計
        for key, mask in pass_masks.items():
            try:
                stats[f"{key}_pass_rate"] = (
                    float(np.mean(mask.astype(float)))
                    if mask is not None and len(mask) > 0
                    else 0.0
                )
            except Exception as e:
                logger.error(f"マスク統計計算エラー ({key}): {e}")
                stats[f"{key}_pass_rate"] = 0.0

        return stats
