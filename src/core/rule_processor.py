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


class RuleBasedProcessor:
    def __init__(self, settings: RuleSettings, callback: Callable[[], None]):
        self.settings = settings
        self.on_snore_detected = callback

        self.sample_rate = 16000
        self.frame_length = 480
        self.hop_length = 240

        self.recent_events: deque = deque(maxlen=20)
        self.candidate_frames_info: list[dict[str, float]] = []

        self.sos_filter = butter(
            N=5, Wn=[80, 1600], btype="bandpass", fs=self.sample_rate, output="sos"
        )

        self._temp_arrays: dict[str, np.ndarray] = {}
        self._init_temp_arrays()

        print("RuleBasedProcessor 初期化完了")

    def _init_temp_arrays(self):
        self._temp_arrays = {}

    def reset_periodicity(self):
        self.recent_events.clear()
        print("周期性イベントキューがリセットされました。")

    def process_audio_chunk(self, audio_chunk: np.ndarray) -> dict[str, Any]:
        filtered_chunk = sosfilt(self.sos_filter, audio_chunk, axis=0)

        try:
            rms = librosa.feature.rms(
                y=filtered_chunk,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            spectral_centroids = librosa.feature.spectral_centroid(
                y=filtered_chunk,
                sr=self.sample_rate,
                n_fft=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            zcrs = librosa.feature.zero_crossing_rate(
                y=filtered_chunk,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            f0, voiced_flag, voiced_probs = librosa.pyin(
                y=filtered_chunk,
                fmin=self.settings.f0_min_hz,
                fmax=self.settings.f0_max_hz,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )
            f0 = np.nan_to_num(f0, nan=0.0)

        except Exception as e:
            print(f"特徴量抽出エラー: {e}")
            return {}

        energy_pass = rms > self.settings.energy_threshold
        f0_confidence_pass = voiced_probs > self.settings.f0_confidence_threshold

        f0_range_pass = np.logical_and(
            np.logical_and(
                self.settings.f0_min_hz <= f0, f0 <= self.settings.f0_max_hz
            ),
            f0 > 0,
        )

        spectral_centroid_pass = (
            spectral_centroids < self.settings.spectral_centroid_threshold
        )
        zcr_pass = zcrs < self.settings.zcr_threshold

        final_pass_mask = np.logical_and.reduce(
            [
                energy_pass,
                f0_confidence_pass,
                f0_range_pass,
                spectral_centroid_pass,
                zcr_pass,
            ]
        )

        mask_changes = np.diff(
            np.concatenate(([False], final_pass_mask, [False])).astype(int)
        )
        starts = np.where(mask_changes == 1)[0]
        ends = np.where(mask_changes == -1)[0]

        for start, end in zip(starts, ends):
            if end > start:  # 有効なセグメント
                segment_rms = rms[start:end]
                segment_f0 = f0[start:end]

                # セグメントの情報を追加
                for i in range(len(segment_rms)):
                    self.candidate_frames_info.append(
                        {"rms": segment_rms[i], "f0": segment_f0[i]}
                    )

                # セグメント終了時に処理
                if self.candidate_frames_info:
                    self._process_event_candidate()
                    self.candidate_frames_info.clear()

        # 最後のセグメントが続いている場合
        if self.candidate_frames_info:
            self._process_event_candidate()
            self.candidate_frames_info.clear()

        analysis_results = {
            "rms": rms,
            "f0_confidence": voiced_probs,
            "f0": f0,
            "spectral_centroid": spectral_centroids,
            "zcr": zcrs,
        }
        pass_masks = {
            "energy": energy_pass,
            "f0_confidence": f0_confidence_pass,
            "f0_range": f0_range_pass,
            "spectral_centroid": spectral_centroid_pass,
            "zcr": zcr_pass,
        }
        self._calculate_detailed_stats(analysis_results, pass_masks)

        return {
            "analysis_results": {
                "rms": rms,
                "f0_confidence": voiced_probs,
                "f0": f0,
                "spectral_centroid": spectral_centroids,
                "zcr": zcrs,
            },
            "pass_masks": pass_masks,  # ★ 追加
            "final_mask_frames": final_pass_mask,
            "recent_events_count": len(self.recent_events),
            "first_event_timestamp": self.recent_events[0].timestamp
            if self.recent_events
            else None,
        }

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

        rms_values = np.array(
            [f["rms"] for f in self.candidate_frames_info], dtype=np.float32
        )
        f0_values = np.array(
            [f["f0"] for f in self.candidate_frames_info], dtype=np.float32
        )

        avg_energy = np.mean(rms_values)
        valid_f0s = f0_values[f0_values > 0]
        avg_f0 = np.mean(valid_f0s) if len(valid_f0s) > 0 else 0.0

        event = SnoreEvent(
            timestamp=datetime.now(),
            duration=event_duration,
            f0=float(avg_f0),
            energy=float(avg_energy),
        )

        self.recent_events.append(event)
        self._check_periodicity()

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
            print(
                f"【いびき検知成功！】周期ウィンドウ内に{len(self.recent_events)}回のイベントを検出"
            )
            self.on_snore_detected()
            self.recent_events.clear()

    def _calculate_detailed_stats(
        self, analysis_results: dict, pass_masks: dict
    ) -> dict:
        stats = {}
        for key, values in analysis_results.items():
            if values is not None and len(values) > 0:
                valid_values = (
                    values[~np.isnan(values)]
                    if np.issubdtype(values.dtype, np.floating)
                    else values
                )
                if len(valid_values) > 0:
                    stats[f"{key}_avg"] = float(np.mean(valid_values))
                    stats[f"{key}_max"] = float(np.max(valid_values))
                    stats[f"{key}_min"] = float(np.min(valid_values))
                else:
                    stats[f"{key}_avg"] = 0.0
                    stats[f"{key}_max"] = 0.0
                    stats[f"{key}_min"] = 0.0

        for key, mask in pass_masks.items():
            if mask is not None and len(mask) > 0:
                stats[f"{key}_pass_rate"] = float(np.mean(mask.astype(float)))
            else:
                stats[f"{key}_pass_rate"] = 0.0

        return stats
