"""合成音声を実際の RuleBasedProcessor に流すエンドツーエンド検証。

チャンクをまたぐフレーム分割の連続性（center=False + 持ち越しサンプル）が
実音声で機能していることを確認する。
- 連続音（ファンの唸りなど）は max_duration で棄却され、検出されない
- 周期的ないびきは検出される
- チャンク境界をまたぐ 1 回のいびきは 1 イベントになる
"""

from datetime import datetime, timedelta

import numpy as np

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings

SR = 16000
T0 = datetime(2026, 1, 1, 0, 0, 0)
AMPLITUDE = 0.3  # RMS が energy_threshold(0.015) を十分に上回る振幅


def _harmonic(num_samples: int, f0: float = 100.0) -> np.ndarray:
    """いびき音を模した低域中心の倍音列（k=1..8、振幅 1/k^2）"""
    t = np.arange(num_samples) / SR
    y = np.zeros(num_samples)
    for k in range(1, 9):
        y += np.sin(2 * np.pi * f0 * k * t) / (k * k)
    y /= np.max(np.abs(y))
    return (y * AMPLITUDE).astype(np.float32)


def _burst(signal: np.ndarray, start_s: float, duration_s: float) -> None:
    """signal の [start_s, start_s+duration_s) にいびき様のバーストを書き込む"""
    start = int(start_s * SR)
    length = int(duration_s * SR)
    tone = _harmonic(length)
    # クリック（急峻な立ち上がり）を避けるため両端 20ms をなだらかにする
    ramp_len = min(int(0.02 * SR), length // 2)
    ramp = np.hanning(2 * ramp_len)
    tone[:ramp_len] *= ramp[:ramp_len]
    tone[length - ramp_len :] *= ramp[ramp_len:]
    signal[start : start + length] = tone


def _run(signal: np.ndarray, on_detected) -> RuleBasedProcessor:
    """1 秒チャンクに切って順に処理する（時刻は固定値から算出して再現性を保つ）"""
    processor = RuleBasedProcessor(RuleSettings(), on_detected, clock=lambda: T0)
    num_chunks = len(signal) // SR
    for i in range(num_chunks):
        processor.process_audio_chunk(
            signal[i * SR : (i + 1) * SR], chunk_start=T0 + timedelta(seconds=i)
        )
    return processor


def test_continuous_hum_does_not_trigger_detection():
    """30 秒続くファンの唸りは 1 度も検出されない"""
    hits = []
    _run(_harmonic(SR * 30), lambda: hits.append(1))
    assert hits == []


def test_periodic_snores_trigger_detection():
    """4 秒周期の 0.8 秒バーストは検出される"""
    hits = []
    signal = np.zeros(SR * 32, dtype=np.float32)
    for n in range(8):
        _burst(signal, start_s=1.0 + 4.0 * n, duration_s=0.8)
    _run(signal, lambda: hits.append(1))
    assert len(hits) >= 1


def test_snore_across_chunk_boundary_is_one_event():
    """チャンク境界をまたぐ 1 回のいびきが 2 分割されない"""
    events = []
    signal = np.zeros(SR * 4, dtype=np.float32)
    _burst(signal, start_s=0.5, duration_s=1.0)
    processor = _run(signal, lambda: None)
    # register_event を通ったイベントは recent_events に残る
    events = list(processor.recent_events)
    assert len(events) == 1
    assert abs(events[0].duration - 1.0) < 0.15
