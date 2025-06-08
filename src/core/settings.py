#!/usr/bin/env python3
"""
SnoreGuard - 設定とデータクラス
仕様書に基づき、ルールベースエンジンのパラメータとイベント情報を管理します。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SnoreEvent:
    """
    検出された個々の「いびき候補イベント」の情報を保持します。
    """

    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0  # 持続時間 (秒)
    f0: float = 0.0  # 平均基本周波数 (Hz)
    energy: float = 0.0  # 平均エネルギー (RMS)


@dataclass
class RuleSettings:
    """
    ルールベースロジックの全パラメータを保持します。
    これらの値は、UIから直接調整されます。
    """

    energy_threshold: float = 0.015
    min_duration_seconds: float = 0.1
    max_duration_seconds: float = 1.0
    f0_min_hz: float = 70.0
    f0_max_hz: float = 150.0
    f0_confidence_threshold: float = 0.05
    spectral_centroid_threshold: float = 500.0
    zcr_threshold: float = 0.06
    periodicity_event_count: int = 4
    periodicity_window_seconds: int = 45
    min_event_interval_seconds: float = 2.0
    max_event_interval_seconds: float = 10.0
