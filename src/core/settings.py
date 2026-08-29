#!/usr/bin/env python3
"""検出ルール・スケジューラの設定データクラスと、その検証ユーティリティ。

注意: このモジュールに ``from __future__ import annotations`` を追加してはいけない。
追加すると dataclasses の ``field.type`` が実際の型ではなく文字列 "int" になり、
sanitized() / from_dict() の ``f.type is int`` 判定が常に False になって、
int のフィールドが float 化してしまう。
"""

import logging
import math
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# UI スライダーの (最小, 最大, 刻み)。検証のクランプにも使う単一のソース。
SLIDER_RANGES: dict[str, tuple[float, float, float]] = {
    "energy_threshold": (0.0, 0.1, 0.001),
    "f0_confidence_threshold": (0.01, 0.4, 0.005),
    "spectral_centroid_threshold": (300, 1500, 10),
    "zcr_threshold": (0.01, 0.15, 0.005),
    "min_duration_seconds": (0.05, 1.0, 0.05),
    "max_duration_seconds": (0.5, 3.0, 0.1),
    # 下限は pyin の探索下限 (PYIN_FMIN_HZ = 50Hz) に合わせる。低い声の
    # いびき（F0 が 70Hz 未満）でも利用者が調整できるようにするため。
    "f0_min_hz": (50, 150, 1),
    "f0_max_hz": (100, 300, 1),
    "periodicity_event_count": (2, 10, 1),
    "periodicity_window_seconds": (10, 120, 1),
    "min_event_interval_seconds": (1.0, 10.0, 0.5),
    "max_event_interval_seconds": (5.0, 20.0, 0.5),
}

FIELD_LABELS: dict[str, str] = {
    "energy_threshold": "エネルギー閾値",
    "f0_confidence_threshold": "F0信頼度閾値",
    "spectral_centroid_threshold": "スペクトル重心閾値",
    "zcr_threshold": "ZCR閾値",
    "min_duration_seconds": "最小持続時間(s)",
    "max_duration_seconds": "最大持続時間(s)",
    "f0_min_hz": "F0最小値(Hz)",
    "f0_max_hz": "F0最大値(Hz)",
    "periodicity_event_count": "周期イベント数",
    "periodicity_window_seconds": "周期ウィンドウ(s)",
    "min_event_interval_seconds": "最小イベント間隔(s)",
    "max_event_interval_seconds": "最大イベント間隔(s)",
}

F0_MIN_GAP_HZ = 20.0  # f0_min と f0_max の最小間隔


@dataclass
class SnoreEvent:
    """検出されたいびきイベント（発生時刻、持続時間、平均 F0、平均エネルギー）"""

    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0
    f0: float = 0.0
    energy: float = 0.0


@dataclass
class RuleSettings:
    """いびき検出アルゴリズムのパラメータ。

    このオブジェクトは検出エンジン（RuleBasedProcessor 配下）と UI で共有される。
    値を差し替えるときは新しいインスタンスを代入せず copy_from() を使うこと。
    """

    energy_threshold: float = 0.015
    f0_confidence_threshold: float = 0.05
    spectral_centroid_threshold: float = 500.0
    zcr_threshold: float = 0.06
    min_duration_seconds: float = 0.2
    max_duration_seconds: float = 3.0
    f0_min_hz: float = 70.0
    f0_max_hz: float = 150.0
    periodicity_event_count: int = 4
    periodicity_window_seconds: int = 45
    min_event_interval_seconds: float = 2.0
    max_event_interval_seconds: float = 10.0

    def copy_from(self, other: "RuleSettings") -> None:
        """全フィールドを other からコピーする（参照は維持）"""
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleSettings":
        """JSON 由来の辞書から生成。型変換に失敗した値は既定値、未知キーは無視。"""
        settings = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            # bool は int のサブクラスなので数値変換に成功してしまう。数値として扱わない。
            if isinstance(raw, bool):
                logger.warning(f"設定 {f.name} の値 {raw!r} が不正なため既定値を使用")
                continue
            try:
                value = int(raw) if f.type is int else float(raw)
            except (TypeError, ValueError):
                logger.warning(f"設定 {f.name} の値 {raw!r} が不正なため既定値を使用")
                continue
            # NaN / inf は JSON からも入りうるが、クランプを素通りするので拒否する。
            if not math.isfinite(value):
                logger.warning(f"設定 {f.name} の値 {raw!r} が不正なため既定値を使用")
                continue
            setattr(settings, f.name, value)
        return settings.sanitized()

    def sanitized(self) -> "RuleSettings":
        """スライダー範囲にクランプし、相互制約を満たした新しいインスタンスを返す"""
        s = RuleSettings()
        s.copy_from(self)
        for f in fields(RuleSettings):
            lo, hi, _step = SLIDER_RANGES[f.name]
            value = getattr(s, f.name)
            # 数値でない値・NaN・inf はクランプできないので既定値に戻す。
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                logger.warning(f"設定 {f.name} の値 {value!r} が不正なため既定値を使用")
                value = f.default
            clamped = min(max(value, lo), hi)
            # 型は宣言（f.type）に合わせる。UI は int/float でスライダー種別を決めるため。
            setattr(s, f.name, int(round(clamped)) if f.type is int else float(clamped))

        if s.f0_min_hz + F0_MIN_GAP_HZ > s.f0_max_hz:
            s.f0_max_hz = min(
                s.f0_min_hz + F0_MIN_GAP_HZ, SLIDER_RANGES["f0_max_hz"][1]
            )
            # 防御的: 現在の SLIDER_RANGES では f0_max の上限に余裕があり到達しない。
            # SLIDER_RANGES を狭めたときのためのフォールバック。
            if s.f0_min_hz + F0_MIN_GAP_HZ > s.f0_max_hz:
                s.f0_min_hz = max(
                    s.f0_max_hz - F0_MIN_GAP_HZ, SLIDER_RANGES["f0_min_hz"][0]
                )
        if s.min_duration_seconds > s.max_duration_seconds:
            s.max_duration_seconds = s.min_duration_seconds
        if s.min_event_interval_seconds > s.max_event_interval_seconds:
            s.max_event_interval_seconds = s.min_event_interval_seconds
        # 防御的: 現在の SLIDER_RANGES の下限は 2 なので到達しない（範囲変更時の保険）。
        s.periodicity_event_count = max(1, s.periodicity_event_count)
        return s

    def validate(self) -> list[str]:
        """問題点の一覧を返す（空なら OK）"""
        problems: list[str] = []
        for name, (lo, hi, _step) in SLIDER_RANGES.items():
            value = getattr(self, name)
            if not (lo <= value <= hi):
                problems.append(f"{name}={value} が範囲 [{lo}, {hi}] 外")
        # sanitized() が強制する間隔と同じ条件で報告する（validate() == [] なら
        # sanitized() は値を変えない、という関係を保つため）。
        if self.f0_min_hz + F0_MIN_GAP_HZ > self.f0_max_hz:
            problems.append(
                f"f0_min_hz({self.f0_min_hz}) と f0_max_hz({self.f0_max_hz}) の間隔が "
                f"{F0_MIN_GAP_HZ}Hz 未満"
            )
        if self.min_duration_seconds > self.max_duration_seconds:
            problems.append("min_duration_seconds > max_duration_seconds")
        if self.min_event_interval_seconds > self.max_event_interval_seconds:
            problems.append("min_event_interval_seconds > max_event_interval_seconds")
        # 防御的: 現在の SLIDER_RANGES の下限は 2 なので範囲チェックが先に検出する。
        if self.periodicity_event_count < 1:
            problems.append("periodicity_event_count < 1")
        return problems

    def diff(self, other: "RuleSettings") -> list[tuple[str, str, Any, Any]]:
        """self → other で変化したフィールドを (name, label, old, new) で返す"""
        changes = []
        for f in fields(self):
            old, new = getattr(self, f.name), getattr(other, f.name)
            if abs(float(old) - float(new)) > 1e-6:
                changes.append((f.name, FIELD_LABELS[f.name], old, new))
        return changes


def format_setting_value(value: Any) -> str:
    """スライダー横・差分表示用の数値整形（int はそのまま、float は最大 4 桁）"""
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


@dataclass
class TimeSchedulerSettings:
    """タイムスケジューラーの設定"""

    enabled: bool = False
    start_time: str = "22:00"
    end_time: str = "06:00"
