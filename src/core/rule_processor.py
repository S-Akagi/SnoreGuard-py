import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import librosa
import numpy as np
from scipy.signal import butter, sosfilt

from core.settings import RuleSettings, SnoreEvent

logger = logging.getLogger(__name__)


# ルールベースのイベント検知
class RuleBasedProcessor:
    def __init__(self, settings: RuleSettings, callback: Callable[[], None]):
        self.settings = settings  # 設定
        self.on_snore_detected = callback  # イベント検知コールバック

        self.sample_rate = 16000  # サンプリングレート
        self.frame_length = 480  # フレーム長
        self.hop_length = 240  # ホップ長

        self.recent_events: deque = deque(maxlen=20)  # 最近のイベント
        self.candidate_frames_info: list[dict[str, float]] = []  # 候補フレーム情報

        self.max_frames = int(
            self.sample_rate * 5.0 / self.hop_length
        )  # 5秒分のフレーム数
        self._rms_buffer = np.zeros(self.max_frames, dtype=np.float32)  # RMSバッファ
        self._f0_buffer = np.zeros(self.max_frames, dtype=np.float32)  # F0バッファ
        self._centroid_buffer = np.zeros(
            self.max_frames, dtype=np.float32
        )  # スペクトル重心バッファ
        self._zcr_buffer = np.zeros(
            self.max_frames, dtype=np.float32
        )  # ゼロ交差率バッファ
        self._voiced_probs_buffer = np.zeros(
            self.max_frames, dtype=np.float32
        )  # 有声確率バッファ

        # ソフトウェアフィルター
        self.sos_filter = butter(
            N=5, Wn=[80, 1600], btype="bandpass", fs=self.sample_rate, output="sos"
        )

        self._temp_arrays: dict[str, np.ndarray] = {}
        self._init_temp_arrays()

        self._warmup_librosa()

        logger.debug("RuleBasedProcessor 初期化完了")

    def _warmup_librosa(self):
        try:
            logger.debug("librosa機能をプリコンパイル中...")
            dummy_audio = np.random.random(self.sample_rate // 10).astype(
                np.float32
            )  # 0.1秒分

            # RMSのプリコンパイル
            _ = librosa.feature.rms(
                y=dummy_audio,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )

            # スペクトル重心のプリコンパイル
            _ = librosa.feature.spectral_centroid(
                y=dummy_audio,
                sr=self.sample_rate,
                n_fft=self.frame_length,
                hop_length=self.hop_length,
            )

            # ゼロ交差率のプリコンパイル
            _ = librosa.feature.zero_crossing_rate(
                y=dummy_audio,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )

            # F0のプリコンパイル
            _ = librosa.pyin(
                y=dummy_audio,
                fmin=self.settings.f0_min_hz,
                fmax=self.settings.f0_max_hz,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )

            logger.debug("librosaプリコンパイル完了")
        except Exception as e:
            logger.error(f"librosaプリコンパイル中にエラー: {e}")

    # 一時的な配列の初期化
    def _init_temp_arrays(self):
        self._temp_arrays = {
            "energy_mask": np.zeros(self.max_frames, dtype=bool),
            "f0_conf_mask": np.zeros(self.max_frames, dtype=bool),
            "f0_range_mask": np.zeros(self.max_frames, dtype=bool),
            "centroid_mask": np.zeros(self.max_frames, dtype=bool),
            "zcr_mask": np.zeros(self.max_frames, dtype=bool),
            "final_mask": np.zeros(self.max_frames, dtype=bool),
        }

    # 周期性イベントキューのリセット
    def reset_periodicity(self):
        self.recent_events.clear()
        logger.debug("周期性イベントキューがリセットされました。")

    # 音声チャンクの処理
    def process_audio_chunk(self, audio_chunk: np.ndarray) -> dict[str, Any]:
        filtered_chunk = sosfilt(self.sos_filter, audio_chunk, axis=0)

        try:
            # 特徴量抽出
            features = self._extract_features_safe(filtered_chunk)
            if not features:
                return {}

            rms = features["rms"]
            spectral_centroids = features["spectral_centroid"]
            zcrs = features["zcr"]
            f0 = features["f0"]
            voiced_probs = features["voiced_probs"]

        except Exception as e:
            logger.error(f"特徴量抽出エラー: {e}")
            return {}

        # マスク操作のための事前割り当てされた配列を使用
        num_frames = len(rms)
        if num_frames > self.max_frames:
            logger.warning(
                f"フレーム数が最大値を超過 ({num_frames} > {self.max_frames})"
            )
            num_frames = self.max_frames
            rms = rms[:num_frames]
            spectral_centroids = spectral_centroids[:num_frames]
            zcrs = zcrs[:num_frames]
            f0 = f0[:num_frames]
            voiced_probs = voiced_probs[:num_frames]

        # 静的なsetitemエラーを避けるために安全な配列操作を使用
        self._temp_arrays["energy_mask"][:num_frames] = (
            rms > self.settings.energy_threshold
        )
        self._temp_arrays["f0_conf_mask"][:num_frames] = (
            voiced_probs > self.settings.f0_confidence_threshold
        )

        # F0の範囲チェック
        f0_valid = np.logical_and(
            f0 > 0,
            np.logical_and(
                f0 >= self.settings.f0_min_hz, f0 <= self.settings.f0_max_hz
            ),
        )
        self._temp_arrays["f0_range_mask"][:num_frames] = f0_valid

        self._temp_arrays["centroid_mask"][:num_frames] = (
            spectral_centroids < self.settings.spectral_centroid_threshold
        )
        self._temp_arrays["zcr_mask"][:num_frames] = zcrs < self.settings.zcr_threshold

        # マスクを結合
        final_pass_mask = np.logical_and.reduce(
            [
                self._temp_arrays["energy_mask"][:num_frames],
                self._temp_arrays["f0_conf_mask"][:num_frames],
                self._temp_arrays["f0_range_mask"][:num_frames],
                self._temp_arrays["centroid_mask"][:num_frames],
                self._temp_arrays["zcr_mask"][:num_frames],
            ]
        )

        # セグメントの処理
        mask_changes = np.diff(
            np.concatenate(([False], final_pass_mask, [False])).astype(int)
        )
        starts = np.where(mask_changes == 1)[0]
        ends = np.where(mask_changes == -1)[0]

        for start, end in zip(starts, ends):
            if end > start:
                segment_rms = [rms[i] for i in range(start, end)]
                segment_f0 = [f0[i] for i in range(start, end)]

                # セグメント情報を追加
                for i in range(len(segment_rms)):
                    self.candidate_frames_info.append(
                        {"rms": float(segment_rms[i]), "f0": float(segment_f0[i])}
                    )

                if self.candidate_frames_info:
                    self._process_event_candidate()
                    self.candidate_frames_info.clear()

        if self.candidate_frames_info:
            self._process_event_candidate()
            self.candidate_frames_info.clear()

        # コピーを使用して返却マスクを作成
        pass_masks = {
            "energy": self._temp_arrays["energy_mask"][:num_frames].copy(),
            "f0_confidence": self._temp_arrays["f0_conf_mask"][:num_frames].copy(),
            "f0_range": self._temp_arrays["f0_range_mask"][:num_frames].copy(),
            "spectral_centroid": self._temp_arrays["centroid_mask"][:num_frames].copy(),
            "zcr": self._temp_arrays["zcr_mask"][:num_frames].copy(),
        }

        analysis_results = {
            "rms": rms.copy() if hasattr(rms, "copy") else rms,
            "f0_confidence": voiced_probs.copy()
            if hasattr(voiced_probs, "copy")
            else voiced_probs,
            "f0": f0.copy() if hasattr(f0, "copy") else f0,
            "spectral_centroid": spectral_centroids.copy()
            if hasattr(spectral_centroids, "copy")
            else spectral_centroids,
            "zcr": zcrs.copy() if hasattr(zcrs, "copy") else zcrs,
        }

        self._calculate_detailed_stats(analysis_results, pass_masks)

        return {
            "analysis_results": analysis_results,
            "pass_masks": pass_masks,
            "final_mask_frames": final_pass_mask.copy(),
            "recent_events_count": len(self.recent_events),
            "first_event_timestamp": self.recent_events[0].timestamp
            if self.recent_events
            else None,
        }

    # 安全な特徴量抽出
    def _extract_features_safe(self, filtered_chunk: np.ndarray) -> dict:
        features = {}

        try:
            # RMSの抽出
            rms = librosa.feature.rms(
                y=filtered_chunk,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            features["rms"] = rms
        except Exception as e:
            logger.error(f"RMS抽出エラー: {e}")
            # エネルギー計算のフォールバック
            hop_samples = len(filtered_chunk) // 20  # 20フレーム分
            rms_fallback = []
            for i in range(0, len(filtered_chunk), hop_samples):
                window = filtered_chunk[i : i + hop_samples]
                if len(window) > 0:
                    rms_fallback.append(np.sqrt(np.mean(window**2)))
            features["rms"] = np.array(rms_fallback, dtype=np.float32)

        try:
            # スペクトル重心の抽出
            spectral_centroids = librosa.feature.spectral_centroid(
                y=filtered_chunk,
                sr=self.sample_rate,
                n_fft=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            features["spectral_centroid"] = spectral_centroids
        except Exception as e:
            logger.error(f"スペクトル重心抽出エラー: {e}")
            # メディアン周波数の使用
            features["spectral_centroid"] = np.full(
                len(features.get("rms", [0])), self.sample_rate / 4, dtype=np.float32
            )

        try:
            # ゼロ交差率の抽出
            zcrs = librosa.feature.zero_crossing_rate(
                y=filtered_chunk,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            features["zcr"] = zcrs
        except Exception as e:
            logger.error(f"ゼロ交差率抽出エラー: {e}")
            # ゼロ交差率の計算のフォールバック
            features["zcr"] = np.full(
                len(features.get("rms", [0])), 0.1, dtype=np.float32
            )

        try:
            # F0の抽出
            f0, voiced_flag, voiced_probs = librosa.pyin(
                y=filtered_chunk,
                fmin=self.settings.f0_min_hz,
                fmax=self.settings.f0_max_hz,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )
            f0 = np.nan_to_num(f0, nan=0.0)
            features["f0"] = f0
            features["voiced_probs"] = voiced_probs
        except Exception as e:
            logger.error(f"F0抽出エラー: {e}")
            # デフォルト値の使用
            rms_len = len(features.get("rms", [0]))
            features["f0"] = np.zeros(rms_len, dtype=np.float32)
            features["voiced_probs"] = np.zeros(rms_len, dtype=np.float32)

        return features

    # イベント候補の処理
    def _process_event_candidate(self):
        num_frames = len(self.candidate_frames_info)
        if num_frames == 0:
            return

        event_duration = num_frames * self.hop_length / self.sample_rate

        if not (
            self.settings.min_duration_seconds
            <= event_duration
            <= self.settings.max_duration_seconds
        ):
            return

        # 静的なsetitemエラーを避けるために安全な配列操作を使用
        try:
            rms_list = [f["rms"] for f in self.candidate_frames_info]
            f0_list = [f["f0"] for f in self.candidate_frames_info]

            rms_values = np.array(rms_list, dtype=np.float32)
            f0_values = np.array(f0_list, dtype=np.float32)
        except Exception as e:
            logger.error(f"配列作成エラー: {e}")
            return

        avg_energy = float(np.mean(rms_values))
        valid_f0s = f0_values[f0_values > 0]
        avg_f0 = float(np.mean(valid_f0s)) if len(valid_f0s) > 0 else 0.0

        event = SnoreEvent(
            timestamp=datetime.now(),
            duration=event_duration,
            f0=avg_f0,
            energy=avg_energy,
        )

        self.recent_events.append(event)
        self._check_periodicity()

    # 周期性のチェック
    def _check_periodicity(self):
        now = datetime.now()
        window_start_time = now - timedelta(
            seconds=self.settings.periodicity_window_seconds
        )

        while (
            self.recent_events and self.recent_events[0].timestamp < window_start_time
        ):
            self.recent_events.popleft()

        if len(self.recent_events) >= self.settings.periodicity_event_count:
            logger.info(
                f"いびき検知成功！周期ウィンドウ内に{len(self.recent_events)}回のイベントを検出"
            )
            self.on_snore_detected()
            self.recent_events.clear()

    # 詳細な統計の計算
    def _calculate_detailed_stats(
        self, analysis_results: dict, pass_masks: dict
    ) -> dict:
        stats = {}
        for key, values in analysis_results.items():
            if values is not None and len(values) > 0:
                try:
                    # 安全な統計計算
                    if hasattr(values, "dtype") and np.issubdtype(
                        values.dtype, np.floating
                    ):
                        valid_values = values[~np.isnan(values)]
                    else:
                        valid_values = values

                    if len(valid_values) > 0:
                        stats[f"{key}_avg"] = float(np.mean(valid_values))
                        stats[f"{key}_max"] = float(np.max(valid_values))
                        stats[f"{key}_min"] = float(np.min(valid_values))
                    else:
                        stats[f"{key}_avg"] = 0.0
                        stats[f"{key}_max"] = 0.0
                        stats[f"{key}_min"] = 0.0
                except Exception as e:
                    logger.error(f"統計計算エラー ({key}): {e}")
                    stats[f"{key}_avg"] = 0.0
                    stats[f"{key}_max"] = 0.0
                    stats[f"{key}_min"] = 0.0

        for key, mask in pass_masks.items():
            if mask is not None and len(mask) > 0:
                try:
                    stats[f"{key}_pass_rate"] = float(np.mean(mask.astype(float)))
                except Exception as e:
                    logger.error(f"マスク統計計算エラー ({key}): {e}")
                    stats[f"{key}_pass_rate"] = 0.0
            else:
                stats[f"{key}_pass_rate"] = 0.0

        return stats
