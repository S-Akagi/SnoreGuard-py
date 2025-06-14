#!/usr/bin/env python3

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SnoreEvent:
    """
    - 検出されたいびきイベントの情報を格納するデータクラス
    - 各いびきイベントには発生時刻、持続時間、音響特徴量（基本周波数、エネルギー）
     などの詳細情報が記録される
    """

    timestamp: datetime = field(default_factory=datetime.now)  # イベント発生時刻
    duration: float = 0.0  # 持続時間 (秒)
    f0: float = 0.0  # 平均基本周波数 (Hz)
    energy: float = 0.0  # 平均エネルギー (RMS)


@dataclass
class RuleSettings:
    """
    - いびき検出アルゴリズムのパラメータ設定を管理するデータクラス
    - 音響特徴量の閾値や時間的制約、周期性検出のパラメータなど、
     いびき検出の精度を調整するための設定値を一元管理する
    """

    # 音響特徴量の閾値設定
    energy_threshold: float = 0.015  # 音声エネルギー閾値（RMS値）
    f0_confidence_threshold: float = 0.05  # 基本周波数の信頼度閾値
    spectral_centroid_threshold: float = 500.0  # スペクトル重心閾値（Hz）
    zcr_threshold: float = 0.06  # ゼロ交差率閾値

    # 時間的制約設定
    min_duration_seconds: float = 0.2  # いびき音の最小持続時間（秒）
    max_duration_seconds: float = 3.0  # いびき音の最大持続時間（秒）

    # 基本周波数の範囲設定
    f0_min_hz: float = 70.0  # いびき音として認識する最低基本周波数（Hz）
    f0_max_hz: float = 150.0  # いびき音として認識する最高基本周波数（Hz）

    # 周期性検出のパラメータ設定
    periodicity_event_count: int = 4  # 周期的いびきと判定するための最小イベント数
    periodicity_window_seconds: int = 45  # 周期性を評価する時間窓（秒）
    min_event_interval_seconds: float = 2.0  # いびきイベント間の最小間隔（秒）
    max_event_interval_seconds: float = 10.0  # いびきイベント間の最大間隔（秒）


@dataclass
class TimeSchedulerSettings:
    """
    タイムスケジューラーの設定を管理するデータクラス
    """

    enabled: bool = False  # スケジューラー有効/無効
    start_time: str = "22:00"  # 開始時刻（HH:MM形式）
    end_time: str = "06:00"  # 終了時刻（HH:MM形式）
