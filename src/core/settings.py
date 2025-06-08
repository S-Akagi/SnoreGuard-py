#!/usr/bin/env python3

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SnoreEvent:
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0  # 持続時間 (秒)
    f0: float = 0.0  # 平均基本周波数 (Hz)
    energy: float = 0.0  # 平均エネルギー (RMS)


@dataclass
class RuleSettings:
    energy_threshold: float = 0.015  # エネルギー閾値
    min_duration_seconds: float = 0.1  # 最小持続時間
    max_duration_seconds: float = 1.0  # 最大持続時間
    f0_min_hz: float = 70.0  # 最低基本周波数
    f0_max_hz: float = 150.0  # 最高基本周波数
    f0_confidence_threshold: float = 0.05  # F0信頼度閾値
    spectral_centroid_threshold: float = 500.0  # スペクトル重心閾値
    zcr_threshold: float = 0.06  # ゼロ交差率閾値
    periodicity_event_count: int = 4  # 周期性イベント数
    periodicity_window_seconds: int = 45  # 周期性ウィンドウ秒
    min_event_interval_seconds: float = 2.0  # 最小イベント間隔秒
    max_event_interval_seconds: float = 10.0  # 最大イベント間隔秒
