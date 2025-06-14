#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SnoreGuard 自動キャリブレーション機能
"""

import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Callable

import librosa
import numpy as np
import sounddevice as sd
from scipy.signal import butter, sosfilt

from core.settings import RuleSettings

logger = logging.getLogger(__name__)


@dataclass
class AudioSample:
    """音声サンプルデータ"""

    label: str  # "silence", "breathing", "snore", "conversation"
    audio_data: np.ndarray
    features: Dict[str, np.ndarray]
    statistics: Dict[str, float]


@dataclass
class CalibrationResult:
    """キャリブレーション結果"""

    optimal_settings: RuleSettings
    confidence_scores: Dict[str, float]
    feature_analysis: Dict[str, Dict[str, float]]
    separation_quality: Dict[str, float]


class StageRecorder:
    """段階的録音システム (UI統合版)"""

    def __init__(self, sample_rate: int = 16000, app_instance=None):
        self.sample_rate = sample_rate
        self.audio_chunk_buffer = []
        self.is_recording = False
        self.app_instance = app_instance

        # UIイベント用のコールバック
        self.progress_callback: Optional[Callable] = None
        self.volume_callback: Optional[Callable] = None
        self.completion_callback: Optional[Callable] = None

        # デバイスIDは録音開始時に動的に取得する

    def _audio_callback(self, indata, frames, time, status):
        """リアルタイムで音声データを受け取るコールバック関数"""
        if status:
            logger.warning(f"録音ステータス: {status}")

        if self.is_recording:
            self.audio_chunk_buffer.append(indata.copy())

            # リアルタイム音量表示用のコールバック
            if self.volume_callback:
                rms_level = np.sqrt(np.mean(indata**2))
                self.volume_callback(rms_level)

    def set_callbacks(
        self, progress_callback=None, volume_callback=None, completion_callback=None
    ):
        """UIコールバックを設定"""
        self.progress_callback = progress_callback
        self.volume_callback = volume_callback
        self.completion_callback = completion_callback

    def record_stage_async(self, stage_name: str, duration: float) -> bool:
        """非同期段階的録音実行"""
        try:
            # 録音開始時に現在選択されているデバイスを動的に取得
            device_id = self._select_device()
        except Exception as e:
            logger.error(f"録音デバイス選択エラー: {e}")
            return False

        try:
            self.audio_chunk_buffer = []
            self.is_recording = True

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                device=device_id,
                callback=self._audio_callback,
            ):
                start_time = time.time()
                while time.time() - start_time < duration and self.is_recording:
                    elapsed = time.time() - start_time
                    progress = elapsed / duration

                    if self.progress_callback:
                        self.progress_callback(progress, duration - elapsed)

                    time.sleep(0.1)

            self.is_recording = False

            if not self.audio_chunk_buffer:
                logger.error("音声データが取得できませんでした")
                return False

            # チャンクを結合して1つの音声データにする
            audio_data = (
                np.concatenate(self.audio_chunk_buffer, axis=0)
                .flatten()
                .astype(np.float32)
            )

            # 品質チェック
            rms_level = np.sqrt(np.mean(audio_data**2))
            max_amplitude = np.max(np.abs(audio_data))

            logger.info(
                f"録音品質 - RMS: {rms_level:.4f}, Max振幅: {max_amplitude:.3f}"
            )

            if self.completion_callback:
                self.completion_callback(audio_data, rms_level, max_amplitude)

            return True

        except Exception as e:
            logger.error(f"録音エラー: {e}")
            self.is_recording = False
            return False

    def stop_recording(self):
        """録音停止"""
        self.is_recording = False

    def _select_device(self) -> int:
        """ダッシュボードの選択デバイスを使用"""
        # アプリインスタンスが設定されている場合、ダッシュボードの選択デバイスを使用
        if self.app_instance and hasattr(self.app_instance, 'mic_var') and hasattr(self.app_instance, 'input_devices'):
            try:
                selected_mic_name = self.app_instance.mic_var.get()
                logger.debug(f"現在の選択デバイス名: {selected_mic_name}")
                logger.debug(f"利用可能デバイス: {list(self.app_instance.input_devices.keys())}")
                
                if selected_mic_name and selected_mic_name in self.app_instance.input_devices:
                    device_id = self.app_instance.input_devices[selected_mic_name]
                    logger.info(f"ダッシュボード選択デバイスを使用: {selected_mic_name} (ID: {device_id})")
                    return int(device_id)
                else:
                    logger.warning(f"選択されたデバイス '{selected_mic_name}' が利用可能デバイスリストに見つかりません")
            except Exception as e:
                logger.warning(f"ダッシュボード選択デバイスの取得に失敗: {e}")

        # ダッシュボードでデバイスが選択されていない場合はエラー
        raise IOError("ダッシュボードで入力デバイスを選択してください")


class FeatureAnalyzer:
    """音響特徴量分析器 (UI統合版)"""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.frame_length = 480
        self.hop_length = 240
        self.sos_filter = butter(
            N=5, Wn=[80, 1600], btype="bandpass", fs=sample_rate, output="sos"
        )

    def analyze_audio(self, audio_data: np.ndarray, label: str) -> AudioSample:
        """音響特徴量分析"""
        try:
            filtered_audio = sosfilt(self.sos_filter, audio_data)
            features = self._extract_all_features(filtered_audio)
            statistics = self._calculate_statistics_with_outlier_removal(features)

            return AudioSample(
                label=label,
                audio_data=filtered_audio,
                features=features,
                statistics=statistics,
            )
        except Exception as e:
            logger.error(f"音響特徴量分析エラー: {e}")
            # エラー時は空のサンプルを返す
            return AudioSample(
                label=label, audio_data=audio_data, features={}, statistics={}
            )

    def _extract_all_features(self, audio: np.ndarray) -> Dict[str, np.ndarray]:
        """音響特徴量抽出"""
        features = {}
        try:
            features["rms"] = librosa.feature.rms(
                y=audio, frame_length=self.frame_length, hop_length=self.hop_length
            )[0]

            features["spectral_centroid"] = librosa.feature.spectral_centroid(
                y=audio,
                sr=self.sample_rate,
                n_fft=self.frame_length,
                hop_length=self.hop_length,
            )[0]

            features["zcr"] = librosa.feature.zero_crossing_rate(
                y=audio, frame_length=self.frame_length, hop_length=self.hop_length
            )[0]

            # より安定したf0抽出設定
            f0, voiced_flag, voiced_probs = librosa.pyin(
                y=audio,
                fmin=50,
                fmax=400,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )

            features["f0"] = np.nan_to_num(f0, nan=0.0)
            features["voiced_probs"] = voiced_probs

        except Exception as e:
            logger.error(f"特徴量抽出エラー: {e}")
            # エラー時はゼロ配列で初期化
            n_frames = max(1, len(audio) // self.hop_length)
            for key in ["rms", "spectral_centroid", "zcr", "f0", "voiced_probs"]:
                features[key] = np.zeros(n_frames)

        return features

    def _calculate_statistics_with_outlier_removal(
        self, features: Dict[str, np.ndarray]
    ) -> Dict[str, float]:
        """外れ値除去を含む統計計算"""
        statistics = {}
        for feature_name, values in features.items():
            if len(values) > 0:
                # ゼロやNaNなどの無効な値を除外
                if feature_name in ["f0", "rms"]:
                    valid_values = values[values > 1e-6]
                else:
                    valid_values = values[~np.isnan(values)]

                if len(valid_values) > 0:
                    # IQR法による外れ値除去
                    Q1 = np.percentile(valid_values, 25)
                    Q3 = np.percentile(valid_values, 75)
                    IQR = Q3 - Q1
                    lower_bound = Q1 - 1.5 * IQR
                    upper_bound = Q3 + 1.5 * IQR

                    # 範囲内の値のみを統計計算の対象とする
                    filtered_values = valid_values[
                        (valid_values >= lower_bound) & (valid_values <= upper_bound)
                    ]

                    # 統計値を計算
                    if len(filtered_values) > 0:
                        statistics[f"{feature_name}_mean"] = float(
                            np.mean(filtered_values)
                        )
                        statistics[f"{feature_name}_std"] = float(
                            np.std(filtered_values)
                        )
                        statistics[f"{feature_name}_p25"] = float(
                            np.percentile(filtered_values, 25)
                        )
                        statistics[f"{feature_name}_p75"] = float(
                            np.percentile(filtered_values, 75)
                        )
                    else:
                        # 外れ値除去後にデータがなくなった場合
                        for stat in ["mean", "std", "p25", "p75"]:
                            statistics[f"{feature_name}_{stat}"] = 0.0
                else:
                    for stat in ["mean", "std", "p25", "p75"]:
                        statistics[f"{feature_name}_{stat}"] = 0.0
        return statistics


class StatisticalCalibrator:
    """統計的キャリブレーター (UI統合版)"""

    def __init__(self):
        self.samples: List[AudioSample] = []

    def add_sample(self, sample: AudioSample):
        """サンプル追加"""
        self.samples.append(sample)
        logger.info(
            f"{sample.label}サンプルを追加（特徴量数: {len(sample.statistics)}）"
        )

    def calculate_optimal_thresholds(self) -> CalibrationResult:
        """最適閾値計算"""
        logger.info("統計分析開始...")

        labels = ["silence", "breathing", "snore", "conversation"]
        sample_counts = {
            label: sum(1 for s in self.samples if s.label == label) for label in labels
        }
        logger.info(f"サンプル数: {sample_counts}")

        feature_analysis = self._analyze_feature_distributions()
        optimal_settings = self._calculate_thresholds(feature_analysis)
        separation_quality = self._evaluate_separation_quality()
        confidence_scores = self._calculate_confidence_scores(separation_quality)

        return CalibrationResult(
            optimal_settings=optimal_settings,
            confidence_scores=confidence_scores,
            feature_analysis=feature_analysis,
            separation_quality=separation_quality,
        )

    def _analyze_feature_distributions(self) -> Dict[str, Dict[str, float]]:
        """特徴量分布分析"""
        feature_analysis = {}
        key_features = ["rms", "spectral_centroid", "zcr", "voiced_probs", "f0"]
        labels = ["silence", "breathing", "snore", "conversation"]

        for feature in key_features:
            feature_analysis[feature] = {}
            for label in labels:
                samples = [s for s in self.samples if s.label == label]
                if samples:
                    values = [s.statistics.get(f"{feature}_mean", 0) for s in samples]
                    for stat in ["mean", "std", "p25", "p75"]:
                        if stat == "std":
                            feature_analysis[feature][f"{label}_{stat}"] = float(
                                np.std(values)
                            )
                        else:
                            percentile = {"mean": 50, "p25": 25, "p75": 75}[stat]
                            feature_analysis[feature][f"{label}_{stat}"] = float(
                                np.percentile(values, percentile)
                            )

        return feature_analysis

    def _calculate_thresholds(self, fa: Dict) -> RuleSettings:
        """閾値計算"""
        settings = RuleSettings()

        # エネルギー閾値の計算
        if "rms" in fa and fa["rms"]:
            noise_floor = fa["rms"].get("silence_mean", 0) + 2 * fa["rms"].get(
                "silence_std", 0
            )
            breathing_level = fa["rms"].get("breathing_mean", 0.01)
            settings.energy_threshold = max(
                0.005, (noise_floor + breathing_level * 0.7) / 2
            )

        # 非いびき音の分布を計算
        non_snore_stats = defaultdict(list)
        for feature in ["spectral_centroid", "zcr", "voiced_probs"]:
            if feature in fa and fa[feature]:
                non_snore_stats[feature].extend(
                    [
                        fa[feature].get("breathing_p75", np.inf),
                        fa[feature].get("conversation_p75", np.inf),
                    ]
                )

        # スペクトル重心、ZCR、F0信頼度の閾値計算
        if "spectral_centroid" in fa and fa["spectral_centroid"]:
            snore_p75 = fa["spectral_centroid"].get("snore_p75", 600)
            non_snore_min = min(non_snore_stats.get("spectral_centroid", [800]))
            settings.spectral_centroid_threshold = (snore_p75 + non_snore_min) / 2

        if "zcr" in fa and fa["zcr"]:
            snore_p75 = fa["zcr"].get("snore_p75", 0.05)
            non_snore_min = min(non_snore_stats.get("zcr", [0.08]))
            settings.zcr_threshold = (snore_p75 + non_snore_min) / 2

        if "voiced_probs" in fa and fa["voiced_probs"]:
            snore_p25 = fa["voiced_probs"].get("snore_p25", 0.3)
            non_snore_max = max(non_snore_stats.get("voiced_probs", [0.03]))
            settings.f0_confidence_threshold = (snore_p25 + non_snore_max) / 2

        # F0範囲の計算
        if "f0" in fa and fa["f0"]:
            snore_mean = fa["f0"].get("snore_mean", 100.0)
            snore_std = fa["f0"].get("snore_std", 10.0)

            if snore_mean > 0:
                margin = max(2.0 * snore_std, 20.0)
                f0_min_calc = snore_mean - margin
                f0_max_calc = snore_mean + margin

                final_f0_min = np.clip(f0_min_calc, 70.0, 150.0)
                final_f0_max = np.clip(f0_max_calc, 100.0, 300.0)

                if final_f0_max < final_f0_min + 20.0:
                    final_f0_max = final_f0_min + 20.0
                    final_f0_max = np.clip(final_f0_max, 100.0, 300.0)

                settings.f0_min_hz = final_f0_min
                settings.f0_max_hz = final_f0_max

        return settings

    def _evaluate_separation_quality(self) -> Dict[str, float]:
        """分離品質評価"""
        quality = {}
        key_features = ["rms", "spectral_centroid", "zcr", "voiced_probs"]

        for feature in key_features:
            separations = []
            for opponent_label in ["breathing", "conversation"]:
                snore_values = [
                    s.statistics.get(f"{feature}_mean", 0)
                    for s in self.samples
                    if s.label == "snore"
                ]
                opponent_values = [
                    s.statistics.get(f"{feature}_mean", 0)
                    for s in self.samples
                    if s.label == opponent_label
                ]

                if snore_values and opponent_values:
                    mean1, std1 = np.mean(snore_values), np.std(snore_values)
                    mean2, std2 = np.mean(opponent_values), np.std(opponent_values)
                    separation = abs(mean1 - mean2) / (std1 + std2 + 1e-6)
                    separations.append(min(1.0, separation / 2.0))

            if separations:
                quality[feature] = np.mean(separations)

        return quality

    def _calculate_confidence_scores(
        self, separation_quality: Dict
    ) -> Dict[str, float]:
        """信頼度スコア計算"""
        scores = {}
        scores["overall_separation"] = (
            np.mean(list(separation_quality.values())) if separation_quality else 0.5
        )

        sample_counts = {
            label: sum(1 for s in self.samples if s.label == label)
            for label in ["silence", "breathing", "snore", "conversation"]
        }
        scores["data_balance"] = (
            1.0 if all(count > 0 for count in sample_counts.values()) else 0.3
        )

        snore_samples = [s for s in self.samples if s.label == "snore"]
        if snore_samples:
            avg_snore_energy = np.mean(
                [s.statistics.get("rms_mean", 0) for s in snore_samples]
            )
            scores["signal_quality"] = min(1.0, avg_snore_energy / 0.02)
        else:
            scores["signal_quality"] = 0.3

        scores["total_confidence"] = (
            scores["overall_separation"] * 0.5
            + scores["data_balance"] * 0.25
            + scores["signal_quality"] * 0.25
        )

        return scores


class AutoCalibrator:
    """自動キャリブレーション統合クラス"""

    def __init__(self, app_instance=None):
        self.recorder = StageRecorder(app_instance=app_instance)
        self.analyzer = FeatureAnalyzer()
        self.calibrator = StatisticalCalibrator()

        # 進行状況トラッキング
        self.current_stage = 0
        self.total_stages = 4
        self.is_calibrating = False

        # VR関連サンプル会話
        self.conversation_samples = [
            "こんにちは皆さん、今日はVRChatで一緒に過ごせて楽しいです。新しいワールドを探検したり、アバターを見せ合ったりしませんか。",
            "VRゲームって本当に素晴らしいですね。現実では体験できない冒険や、世界中の人たちとのコミュニケーションが可能になります。",
            "このSnoreGuardアプリケーションは、VR睡眠中のいびきを自動検出して、フレンドに迷惑をかけないようマイクをミュートしてくれる便利なツールです。",
        ]

        # ステージ定義
        self.stages = [
            ("環境音収集", 10.0, "できるだけ静かな状態を保ってください。", "silence"),
            ("通常呼吸音収集", 15.0, "自然な呼吸をしてください。", "breathing"),
            (
                "軽いいびき音収集",
                15.0,
                "軽いいびき音を意図的に作ってください。",
                "snore",
            ),
            (
                "通常会話収集",
                20.0,
                "マイクに向かって読み上げてください。",
                "conversation",
            ),
        ]

    def get_conversation_text(self) -> str:
        """ランダムな会話サンプルを取得"""
        return random.choice(self.conversation_samples)

    def get_stage_info(self, stage_index: int) -> Tuple[str, float, str, str]:
        """ステージ情報を取得"""
        if 0 <= stage_index < len(self.stages):
            return self.stages[stage_index]
        return ("", 0.0, "", "")

    def start_calibration(self) -> bool:
        """キャリブレーション開始"""
        if self.is_calibrating:
            return False

        self.is_calibrating = True
        self.current_stage = 0
        self.calibrator = StatisticalCalibrator()  # リセット
        return True

    def stop_calibration(self):
        """キャリブレーション停止"""
        self.is_calibrating = False
        self.recorder.stop_recording()

    def process_recorded_audio(self, audio_data: np.ndarray, label: str):
        """録音した音声を処理"""
        if len(audio_data) > 0:
            sample = self.analyzer.analyze_audio(audio_data, label)
            self.calibrator.add_sample(sample)
            return True
        return False

    def get_calibration_result(self) -> Optional[CalibrationResult]:
        """キャリブレーション結果を取得"""
        if len(self.calibrator.samples) >= 3:  # 最低3つのサンプルが必要
            return self.calibrator.calculate_optimal_thresholds()
        return None
