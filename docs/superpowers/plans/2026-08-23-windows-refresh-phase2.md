# SnoreGuard Windows 版改修 — Phase 2 実装計画（無人運転と UI の信頼性）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 で「ミュートが効く」状態にしたうえで、スケジューラによる無人運転・接続状態の表示・自動キャリブレーション・スレッド境界・VRChat 連携・mDNS・HiDPI を、監査の P1 項目どおりに信頼できるものにする。

**Architecture:** (1) アプリ設定は `AppSettings` データクラスを唯一の真のソースとし、`reset` も `apply` も同じ入口を通す。(2) スケジューラは「時間帯内か」をレベルで評価し、非対話経路では失敗時に再試行する。(3) ワーカースレッドから Tk を同期呼び出ししない——通知は `queue` 経由でメインスレッドが排出し、OSC ハンドラはメインスレッドへ委譲するだけにする。(4) キャリブレーションは検出器と同じ `FeatureExtractor` を共用し、フレーム分布で統計を取る。

**Tech Stack:** Phase 1 と同じ。

**Spec:** `docs/superpowers/specs/2026-08-23-windows-refresh-audit.md`（課題 06〜14 および 16 の一部）

## 実行状況（2026-08-23 時点）

**未着手。** 前提の Phase 1 は Task 8 まで完了（HEAD `d3ec881`）、Task 9〜12 が残っている。
Phase 1 を完了させてから本計画に着手すること。Task 14 冒頭に Phase 1 Task 8 からの
持ち越し 2 件（再試行ラダー・初期化中のストリーム死亡）を明記済み。

## Global Constraints

Phase 1 計画の Global Constraints をそのまま適用する（Python 3.11、uv、コミットに Claude 表記なし、`type: 日本語要約`、各タスク末尾で ruff、GUI 変更は import スモーク）。加えて:

- Phase 1 の成果（`RuleSettings.copy_from`、`apply_rule_settings`、`on_stream_stopped`、`mute_policy`、`core.constants`、`notify`、`logging_setup`）を前提にする。Phase 1 が未完了なら先に完了させること。
- **ワーカースレッドから `root.after` / Tk ウィジェット / `messagebox` を直接呼ばない**（`ThreadSafeHandler.safe_after` 経由は可。ただしメインスレッドで `join` している間は呼ばれない構造にする）。
- 新しい設定キーを追加したら `AppSettings` にフィールドを足し、`to_dict/from_dict` とテストを更新する。

---

## ファイル構成（Phase 2 で触るもの）

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/core/settings.py` | 設定 | `AppSettings`、`TimeSchedulerSettings.parse_times/validate/from_dict` |
| `src/snoreguard/time_scheduler.py` | スケジューラ | `is_within_window`、レベル評価、`clock` 注入 |
| `src/snoreguard/app.py` | アプリ | 設定入口統一、origin 付き開始、再試行、接続表示、イベント排出、OSC 委譲先 |
| `src/snoreguard/ui.py` | UI | 接続インジケータ、停止時ミュート解除チェックボックス、ウィンドウサイズ |
| `src/snoreguard/vrc/handler.py` | OSC | 受信時刻記録、デーモン化、委譲、エコー判定、loopback 限定 |
| `src/snoreguard/vrc/echo_filter.py` | **新規** 送受信エコー判定 | |
| `src/snoreguard/vrc/osc_query_service.py` | OSC 送信 | 監視ループ削除・コメント修正 |
| `src/snoreguard/vrc/mdns_client.py` | mDNS | ポインタ検証、SRV ポート通知 |
| `src/snoreguard/audio_service.py` | 音声ワーカー | `event_queue`、非ブロッキング stop |
| `src/snoreguard/auto_calibrator.py` | キャリブレーション | `FeatureExtractor` 共用、フレーム分布統計、方向付き閾値、品質ゲート、キャンセル |
| `src/snoreguard/calibration_modal.py` | モーダル | キャンセル検査、解析をワーカーへ、音量ポーリング、スクロール |
| `src/snoreguard/dpi.py` | **新規** DPI 認識 | |
| `src/main.py` | 起動 | DPI、ウィンドウ設定の UIBuilder 集約 |
| `docs/MANUAL.md`, `README.md` | 文書 | Toggle モード、ミュート解除、ログ位置、9001 競合 |
| `tests/` | テスト | 各タスク |

---

### Task 13: `AppSettings` と設定入口の統一・リセットの完全化

**Files:**
- Modify: `src/core/settings.py`（`TimeSchedulerSettings` 拡張、`AppSettings` 追加）
- Modify: `src/snoreguard/app.py`（`_get_default_settings`, `__init__` の load、`_update_ui_with_settings`, `_save_app_settings`, `reset_settings`, `_start_time_scheduler_if_enabled`, `update_time_scheduler_settings`）
- Test: `tests/test_app_settings.py`

**Interfaces:**
- Produces（`core.settings`）:
  - `TimeSchedulerSettings.from_dict(d) -> TimeSchedulerSettings`、`.parse_times() -> tuple[datetime.time, datetime.time]`（不正なら `ValueError`）、`.validate() -> list[str]`
  - `AppSettings`（fields: `mic_device_name: str`, `audio_notification_enabled: bool`, `auto_mute_on_snore: bool`, `unmute_on_stop: bool`, `rule_settings: RuleSettings`, `time_scheduler: TimeSchedulerSettings`, `settings_version: int = 2`）、`AppSettings.from_dict(d)`、`AppSettings.to_dict() -> dict`
- Consumes: Phase 1 の `RuleSettings.from_dict / apply_rule_settings`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_app_settings.py`:

```python
from datetime import time

import pytest

from core.settings import AppSettings, RuleSettings, TimeSchedulerSettings


def test_roundtrip_to_dict_from_dict():
    s = AppSettings(
        mic_device_name="マイク (USB)",
        audio_notification_enabled=False,
        unmute_on_stop=True,
        rule_settings=RuleSettings(zcr_threshold=0.1),
        time_scheduler=TimeSchedulerSettings(enabled=True, start_time="23:30", end_time="07:00"),
    )
    d = s.to_dict()
    assert d["settings_version"] == 2
    assert d["rule_settings"]["zcr_threshold"] == 0.1
    assert AppSettings.from_dict(d) == s


def test_from_dict_tolerates_missing_and_unknown_keys():
    s = AppSettings.from_dict({"mic_device_name": "x", "bogus": 1})
    assert s.mic_device_name == "x"
    assert s.audio_notification_enabled is True
    assert s.rule_settings == RuleSettings()


def test_from_dict_coerces_types():
    s = AppSettings.from_dict(
        {"audio_notification_enabled": 0, "time_scheduler": {"enabled": "1", "start_time": "9:5"}}
    )
    assert s.audio_notification_enabled is False
    assert s.time_scheduler.enabled is True
    assert s.time_scheduler.start_time == "09:05"


def test_scheduler_invalid_time_falls_back_to_default():
    s = TimeSchedulerSettings.from_dict({"start_time": "25:99", "end_time": "abc"})
    assert s.start_time == "22:00"
    assert s.end_time == "06:00"


def test_parse_times_and_validate():
    assert TimeSchedulerSettings(start_time="22:00", end_time="06:00").parse_times() == (
        time(22, 0),
        time(6, 0),
    )
    with pytest.raises(ValueError):
        TimeSchedulerSettings(start_time="bad").parse_times()
    assert TimeSchedulerSettings(start_time="10:00", end_time="10:00").validate() == [
        "開始時刻と終了時刻が同じです"
    ]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_app_settings.py -q`
Expected: ImportError（`AppSettings` なし）

- [ ] **Step 3: 実装（core/settings.py）**

`TimeSchedulerSettings` を以下に置き換え、その後ろに `AppSettings` を追加する:

```python
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{1,2})$")


def _normalize_hhmm(value: Any, default: str) -> str:
    """'9:5' → '09:05'。不正なら default。"""
    m = _TIME_RE.match(str(value).strip()) if value is not None else None
    if not m:
        return default
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return default
    return f"{hour:02d}:{minute:02d}"


@dataclass
class TimeSchedulerSettings:
    """タイムスケジューラーの設定（HH:MM 文字列で保持）"""

    enabled: bool = False
    start_time: str = "22:00"
    end_time: str = "06:00"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TimeSchedulerSettings":
        data = data or {}
        defaults = cls()
        return cls(
            enabled=_to_bool(data.get("enabled"), defaults.enabled),
            start_time=_normalize_hhmm(data.get("start_time"), defaults.start_time),
            end_time=_normalize_hhmm(data.get("end_time"), defaults.end_time),
        )

    def parse_times(self) -> tuple[dt_time, dt_time]:
        """(開始, 終了) を datetime.time で返す。形式不正なら ValueError。"""
        result = []
        for label, value in (("開始時刻", self.start_time), ("終了時刻", self.end_time)):
            m = _TIME_RE.match(value)
            if not m:
                raise ValueError(f"{label}の形式が不正です: {value!r}")
            result.append(dt_time(int(m.group(1)), int(m.group(2))))
        return result[0], result[1]

    def validate(self) -> list[str]:
        problems = []
        try:
            start, end = self.parse_times()
        except ValueError as e:
            return [str(e)]
        if start == end:
            problems.append("開始時刻と終了時刻が同じです")
        return problems


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


@dataclass
class AppSettings:
    """アプリ全体の永続設定。JSON との変換はここだけが知っている。"""

    mic_device_name: str = ""
    audio_notification_enabled: bool = True
    auto_mute_on_snore: bool = True
    unmute_on_stop: bool = False
    rule_settings: RuleSettings = field(default_factory=RuleSettings)
    time_scheduler: TimeSchedulerSettings = field(default_factory=TimeSchedulerSettings)
    settings_version: int = 2

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppSettings":
        data = data or {}
        defaults = cls()
        return cls(
            mic_device_name=str(data.get("mic_device_name", defaults.mic_device_name) or ""),
            audio_notification_enabled=_to_bool(
                data.get("audio_notification_enabled"), defaults.audio_notification_enabled
            ),
            auto_mute_on_snore=_to_bool(
                data.get("auto_mute_on_snore"), defaults.auto_mute_on_snore
            ),
            unmute_on_stop=_to_bool(data.get("unmute_on_stop"), defaults.unmute_on_stop),
            rule_settings=RuleSettings.from_dict(data.get("rule_settings") or {}),
            time_scheduler=TimeSchedulerSettings.from_dict(data.get("time_scheduler")),
            settings_version=defaults.settings_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings_version": self.settings_version,
            "mic_device_name": self.mic_device_name,
            "audio_notification_enabled": self.audio_notification_enabled,
            "auto_mute_on_snore": self.auto_mute_on_snore,
            "unmute_on_stop": self.unmute_on_stop,
            "rule_settings": asdict(self.rule_settings),
            "time_scheduler": asdict(self.time_scheduler),
        }
```

ファイル先頭の import を `import logging`, `import re`, `from dataclasses import asdict, dataclass, field, fields`, `from datetime import datetime, time as dt_time`, `from typing import Any` にする。

- [ ] **Step 4: app.py を `AppSettings` に寄せる**

`app.py` の import を `from core.settings import AppSettings, RuleSettings, TimeSchedulerSettings, format_setting_value` に。

`_get_default_settings` を:

```python
    def _get_default_settings(self) -> dict:
        """アプリのデフォルト設定値（JSON 形式）"""
        return AppSettings().to_dict()
```

`__init__` の `self.app_settings = self.settings_manager.load(self._get_default_settings())` を:

```python
        raw_settings = self.settings_manager.load(self._get_default_settings())
        # 型・範囲を正規化した辞書を保持する（未知キーは捨てる）
        self.app_settings = AppSettings.from_dict(raw_settings).to_dict()
```

`_update_ui_with_settings` の冒頭 3 行を:

```python
        settings = AppSettings.from_dict(self.app_settings)
        self.notification_var.set(settings.audio_notification_enabled)
        self.auto_mute_var.set(settings.auto_mute_on_snore)
        self.rule_settings.copy_from(settings.rule_settings)
```

（`if self.HAS_OSC:` の分岐と `if rule_settings_dict := ...` ブロックは削除。）

`_start_time_scheduler_if_enabled` と `update_time_scheduler_settings` の時刻パース（`from datetime import time as dt_time` 〜 `dt_time(end_hour, end_minute)`）を両方とも次に置き換える:

```python
            scheduler = TimeSchedulerSettings.from_dict(self.app_settings.get("time_scheduler"))
            start_time, end_time = scheduler.parse_times()
```

（`update_time_scheduler_settings` では先に `self.app_settings["time_scheduler"] = {...}` を代入してから上の 2 行を使う。引数の `start_time`/`end_time` 文字列はそのまま保存する。）

`reset_settings` を以下に置き換える（スケジューラ停止とチェックボックス復帰を含む完全なリセット）:

```python
    def reset_settings(self):
        """設定をすべてデフォルト値に戻す（ルール・通知・自動ミュート・スケジューラ）"""
        if not messagebox.askyesno(
            "設定のリセット",
            "ルール設定・通知・自動ミュート・タイムスケジューラーをすべて初期値に戻します。\nよろしいですか？",
        ):
            return
        try:
            defaults = AppSettings()
            self.notification_var.set(defaults.audio_notification_enabled)
            self.auto_mute_var.set(defaults.auto_mute_on_snore)
            self.update_time_scheduler_settings(
                defaults.time_scheduler.enabled,
                defaults.time_scheduler.start_time,
                defaults.time_scheduler.end_time,
            )
            self._update_scheduler_settings_ui()
            self.apply_rule_settings(defaults.rule_settings, source="リセット")
            self.add_log("設定をデフォルト値にリセットしました", "info")
        except Exception as e:
            logger.error(f"設定リセット中にエラー: {e}", exc_info=True)
            self.add_log(f"設定リセットエラー: {e}", "error")
```

（`self.time_scheduler_settings = TimeSchedulerSettings()` のデッドストアは削除。）

- [ ] **Step 5: テストと import スモーク**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app; print('import ok')"`
Expected: 全 PASS、`import ok`

- [ ] **Step 6: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/core/settings.py tests/test_app_settings.py
git commit -m "feat: AppSettings/TimeSchedulerSettings に JSON 変換と検証を集約"
git add src/snoreguard/app.py
git commit -m "fix: リセットでスケジューラ停止と通知/自動ミュートの復帰も行い、設定の読み書きを AppSettings 経由に統一"
```

---

### Task 14: スケジューラのレベル評価・非対話経路の再試行・開始/停止ガード

**Phase 1 Task 8 からの持ち越し（このタスクで必ず解消する）:**

1. **再試行ラダーが 1 回で止まる。** Phase 1 で入れた `RESTART_DELAYS_S = (5, 10, 20, 40, 60)` の
   自動再開は、`_retry_start_detection` → `_start_detection` → `_initialize_audio_system` の
   デバイス事前テスト（`sd.InputStream(...)`）が失敗すると `_handle_initialization_error` の
   modal `messagebox` で止まり、2 回目以降の遅延と諦め時の `notify.beep(600, 500)` に到達しない。
   本タスクの `origin` 引数（非対話経路ではダイアログを出さず `_schedule_scheduler_retry`）で解消すること。
   `_retry_start_detection` は `self._start_detection(origin="retry")` を呼ぶよう更新する。
2. **初期化中のストリーム死亡が握り潰される。** `audio_service.start()` 直後から
   `_finalize_detection_start` までの窓でワーカーが死ぬと、`_handle_stream_stopped` は
   `app.is_running == False` のため早期 return し、UI は「検出中」のまま動かない検出器が残る。
   `_finalize_detection_start` の先頭に次のガードを追加すること:

```python
        if not self.audio_service.is_running:
            error = self.audio_service.last_error or "音声ストリームを開始できませんでした"
            self.is_initializing = False
            self._handle_initialization_error(error, origin)
            return
```
   （`_finalize_detection_start` は `origin` を受け取るよう `_initialize_audio_system` 側の
   `self.root.after(0, self._finalize_detection_start, selected_mic_name, origin)` に合わせる。）

**Files:**
- Modify: `src/snoreguard/time_scheduler.py`（全体）
- Modify: `src/snoreguard/app.py`（`_start_detection`, `_start_detection_async`, `_initialize_audio_system`, `_handle_initialization_error`, `_stop_detection`, `_scheduler_start_detection`, `_scheduler_stop_detection`, `_retry_start_detection`）
- Test: `tests/test_time_scheduler.py`

**Interfaces:**
- Produces:
  - `time_scheduler.is_within_window(now: time, start: time, end: time) -> bool`（`start == end` は常に False、日跨ぎ対応）
  - `TimeScheduler.__init__(start_callback, stop_callback, clock: Callable[[], datetime] = datetime.now, poll_seconds: float = 1.0)`
  - `TimeScheduler.evaluate(now: datetime | None = None) -> str | None`（`"start"` / `"stop"` / `None`。初回評価で時間帯外なら停止コールバックを呼ばない）
  - `TimeScheduler.wants_running -> bool`（直近評価で時間帯内だったか）
  - `SnoreGuardApp._start_detection(origin: str = "manual")`（`"manual" | "scheduler" | "osc" | "retry"`）。非 manual ではダイアログを出さず、失敗時は 60 秒後に再試行（最大 5 回、スケジューラが時間帯内の間）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_time_scheduler.py`:

```python
from datetime import datetime, time

from snoreguard.time_scheduler import TimeScheduler, is_within_window


def test_window_same_day():
    assert is_within_window(time(12, 0), time(10, 0), time(14, 0))
    assert not is_within_window(time(14, 0), time(10, 0), time(14, 0))
    assert not is_within_window(time(9, 59), time(10, 0), time(14, 0))


def test_window_across_midnight():
    assert is_within_window(time(23, 30), time(22, 0), time(6, 0))
    assert is_within_window(time(2, 0), time(22, 0), time(6, 0))
    assert not is_within_window(time(12, 0), time(22, 0), time(6, 0))


def test_start_equals_end_is_never_inside():
    assert not is_within_window(time(10, 0), time(10, 0), time(10, 0))


def _scheduler(now_holder, calls):
    s = TimeScheduler(
        start_callback=lambda: calls.append("start"),
        stop_callback=lambda: calls.append("stop"),
        clock=lambda: now_holder[0],
    )
    s.configure(True, time(22, 0), time(6, 0))
    return s


def test_evaluate_starts_when_launched_inside_window():
    now, calls = [datetime(2026, 1, 1, 23, 10)], []
    s = _scheduler(now, calls)
    assert s.evaluate() == "start"
    assert s.evaluate() is None  # 変化なし
    now[0] = datetime(2026, 1, 2, 6, 0)
    assert s.evaluate() == "stop"
    assert calls == ["start", "stop"]


def test_first_evaluation_outside_window_does_not_call_stop():
    now, calls = [datetime(2026, 1, 1, 12, 0)], []
    s = _scheduler(now, calls)
    assert s.evaluate() is None
    assert calls == []
    assert s.wants_running is False


def test_sleep_across_start_time_still_starts():
    now, calls = [datetime(2026, 1, 1, 21, 55)], []
    s = _scheduler(now, calls)
    s.evaluate()
    now[0] = datetime(2026, 1, 1, 22, 7)  # 22:00 をスリープで飛ばした
    assert s.evaluate() == "start"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_time_scheduler.py -q`
Expected: ImportError（`is_within_window` なし）

- [ ] **Step 3: `time_scheduler.py` を実装**

ファイル全体を以下に置き換える:

```python
#!/usr/bin/env python3
"""時刻指定での自動検出開始/停止スケジューラー。

「開始時刻ちょうど」のエッジではなく「現在時刻が時間帯内か」をレベルで評価する。
これにより時間帯の途中で起動した場合やスリープ復帰後も正しく開始/停止する。
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, time as dt_time

logger = logging.getLogger(__name__)


def is_within_window(now: dt_time, start: dt_time, end: dt_time) -> bool:
    """now が [start, end) に入っているか。日跨ぎ（22:00→06:00）対応。start==end は常に False。"""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


class TimeScheduler:
    def __init__(
        self,
        start_callback: Callable[[], None],
        stop_callback: Callable[[], None],
        clock: Callable[[], datetime] = datetime.now,
        poll_seconds: float = 1.0,
    ):
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.clock = clock
        self.poll_seconds = poll_seconds

        self.enabled = False
        self.start_time: dt_time | None = None
        self.end_time: dt_time | None = None

        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_desired: bool | None = None  # 直近評価の「時間帯内か」

    @property
    def wants_running(self) -> bool:
        return bool(self._last_desired)

    def configure(
        self, enabled: bool, start_time: dt_time | None, end_time: dt_time | None
    ):
        """設定を更新する。動作中なら一度止めて再開する。"""
        logger.info(
            f"スケジューラー設定更新: enabled={enabled}, start={start_time}, end={end_time}"
        )
        was_running = self._running
        if was_running:
            self.stop()
        self.enabled = enabled
        self.start_time = start_time
        self.end_time = end_time
        self._last_desired = None
        if was_running and enabled:
            self.start()

    def start(self):
        if self._running:
            logger.warning("スケジューラーは既に動作中です")
            return
        if not self.enabled:
            logger.info("スケジューラーが無効化されています")
            return
        if not self.start_time or not self.end_time:
            logger.warning("開始時刻または終了時刻が設定されていません")
            return
        logger.info("スケジューラーを開始します")
        self._running = True
        self._last_desired = None
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._scheduler_loop, daemon=True, name="time-scheduler"
        )
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        logger.info("スケジューラーを停止します")
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def evaluate(self, now: datetime | None = None) -> str | None:
        """現在時刻を評価し、状態が変わればコールバックを呼んで 'start'/'stop' を返す。

        初回評価で時間帯外のときは「停止」を呼ばない（利用者が手動で開始した
        検出を、スケジューラ起動だけで止めないため）。
        """
        if not self.enabled or not self.start_time or not self.end_time:
            return None
        current = (now or self.clock()).time()
        desired = is_within_window(current, self.start_time, self.end_time)
        previous = self._last_desired
        self._last_desired = desired
        if previous is None:
            if desired:
                self._run_callback(self.start_callback, "開始")
                return "start"
            return None
        if desired == previous:
            return None
        if desired:
            self._run_callback(self.start_callback, "開始")
            return "start"
        self._run_callback(self.stop_callback, "停止")
        return "stop"

    def _scheduler_loop(self):
        logger.info("スケジューラーループ開始")
        while self._running and not self._stop_event.is_set():
            try:
                self.evaluate()
            except Exception as e:  # noqa: BLE001 - ループは止めない
                logger.error(f"スケジューラーエラー: {e}", exc_info=True)
            if self._stop_event.wait(self.poll_seconds):
                break
        logger.info("スケジューラーループ終了")

    def _run_callback(self, callback: Callable[[], None], label: str):
        try:
            logger.info(f"スケジューラーによる検出{label}: {self.clock():%H:%M}")
            callback()
        except Exception as e:  # noqa: BLE001
            logger.error(f"スケジューラー検出{label}エラー: {e}", exc_info=True)
```

- [ ] **Step 4: app.py に origin と再試行を入れる**

`__init__` に追加: `self._scheduler_retry_count = 0`、`self._scheduler_retry_after_id = None`。クラス定数 `SCHEDULER_RETRY_DELAY_S = 60`, `SCHEDULER_RETRY_MAX = 5`。

`_start_detection` を以下に置き換える:

```python
    def _start_detection(self, origin: str = "manual"):
        """選択されたマイクで音声検出を開始。origin は manual/scheduler/osc/retry"""
        logger.debug(f"検出開始処理開始 (origin={origin})")
        if self.is_running or self.is_initializing:
            logger.debug("既に検出中/初期化中のためスキップ")
            return
        if self.calibration_modal and self.calibration_modal.modal_window:
            self.add_log("キャリブレーション中は検出を開始できません", "warning")
            return

        selected_mic_name = self.mic_var.get()
        device_id = self.input_devices.get(selected_mic_name) if selected_mic_name else None
        if device_id is None:
            self._report_start_failure("マイクを選択してください。", origin)
            return
        self._start_detection_async(selected_mic_name, device_id, origin)

    def _report_start_failure(self, message: str, origin: str):
        """開始失敗の通知。対話経路だけダイアログ、無人経路は再試行。"""
        self.add_log(f"検出を開始できません: {message}", "error")
        if origin == "manual":
            messagebox.showerror("エラー", message)
            return
        self._schedule_scheduler_retry()

    def _schedule_scheduler_retry(self):
        """スケジューラ/OSC 経路の失敗後、時間帯内である限り一定間隔で再試行"""
        if self._scheduler_retry_after_id:
            return
        if self._scheduler_retry_count >= self.SCHEDULER_RETRY_MAX:
            self.add_log("自動開始の再試行回数を超えました。手動で開始してください。", "error")
            notify.beep(600, 500)
            return
        self._scheduler_retry_count += 1
        self.add_log(
            f"{self.SCHEDULER_RETRY_DELAY_S}秒後に自動開始を再試行します "
            f"({self._scheduler_retry_count}/{self.SCHEDULER_RETRY_MAX})",
            "warning",
        )
        self.status_label_var.set("開始待機中（再試行）")
        self._scheduler_retry_after_id = self.root.after(
            self.SCHEDULER_RETRY_DELAY_S * 1000, self._run_scheduler_retry
        )

    def _run_scheduler_retry(self):
        self._scheduler_retry_after_id = None
        if self.is_running or self.is_initializing:
            return
        if not self.time_scheduler.wants_running:
            self.add_log("時間帯外になったため自動開始の再試行を終了します", "system")
            return
        self._populate_mic_list()
        self._start_detection(origin="retry")
```

`_start_detection_async(self, selected_mic_name, device_id, origin)` と `_initialize_audio_system(self, selected_mic_name, device_id, origin)` に `origin` を引き回し、`_initialize_audio_system` の except 節を `self.root.after(0, self._handle_initialization_error, str(e), origin)` に。`_handle_initialization_error` を:

```python
    def _handle_initialization_error(self, error_message: str, origin: str = "manual"):
        """初期化失敗時の UI リセット。音声サービスは必ず止める。"""
        self.is_initializing = False
        self.is_running = False
        self.audio_service.stop()
        self._update_control_state()
        self.status_label_var.set("初期化失敗")
        self.add_log(f"初期化エラー: {error_message}", "error")
        if origin == "manual":
            messagebox.showerror(
                "初期化エラー", f"音声システムの初期化に失敗しました:\n{error_message}"
            )
        else:
            self._schedule_scheduler_retry()
```

`_finalize_detection_start` の先頭に `self._scheduler_retry_count = 0` を追加。`_stop_detection` の冒頭を:

```python
        if not self.is_running and not self.is_initializing:
            logger.debug("検出は動作していないため停止処理をスキップ")
            return
        if self._scheduler_retry_after_id:
            self.root.after_cancel(self._scheduler_retry_after_id)
            self._scheduler_retry_after_id = None
```

`_scheduler_start_detection` の `safe_after(self.root, self._start_detection)` を `safe_after(self.root, self._start_detection, "scheduler")` に。Phase 1 Task 8 の `_retry_start_detection` 内の `self._start_detection()` を `self._start_detection(origin="retry")` に。

- [ ] **Step 5: テストと import スモーク**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app; print('import ok')"`
Expected: 全 PASS、`import ok`

- [ ] **Step 6: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/time_scheduler.py tests/test_time_scheduler.py
git commit -m "fix: スケジューラを時間帯のレベル評価に変更し、時間帯内起動やスリープ復帰でも開始/停止する"
git add src/snoreguard/app.py
git commit -m "fix: 無人経路（スケジューラ/OSC）の開始失敗はダイアログを出さず再試行し、開始/停止に状態ガードを追加"
```

---

### Task 15: VRChat 接続状態を実測で表示し、検出状態ラベルと分離する

**Phase 1 Task 9 からの持ち越し:** 受信ポート bind 失敗時の赤ラベル（`_warn_receiver_unavailable`）は
`_update_osc_status_ui` からの上書きこそ防いだが、検出ライフサイクル側の `status_label_var.set`
（「検出中」「音声入力エラー」「システム待機中」「イビキ検出!」）には依然として消される。本タスクで
VRChat 接続状態を独立した `vrc_status_var` インジケータに分離すれば構造的に解消するので、
分離後は `_warn_receiver_unavailable` から `status_label` / `status_label_var` の操作を削除し、
`receiver_down` 状態は `_poll_vrc_status` の表示に一本化すること（`_update_osc_status_ui` の
`receiver_ok` 早期 return も同時に不要になる）。

**Phase 1 Task 8 からの持ち越し（Minor）:** `_check_silence` は無音検知時に
`status_label_var` を「⚠ 無音が続いています」にするが、音声が戻っても復帰ログを出すだけで
文言を戻さない。本タスクで `_set_detection_status` を導入する際、復帰分岐（`_silence_warned`
を False に戻す箇所）で `self._set_detection_status("🔊 検出中...", "#1F6AA5")` を呼ぶこと。

**Files:**
- Modify: `src/snoreguard/vrc/handler.py`（`VRChatOSCReceiver` に受信時刻、`VRCHandler.connection_state`）
- Modify: `src/snoreguard/vrc/osc_query_service.py`（監視ループ削除、コメント修正）
- Modify: `src/snoreguard/ui.py:354-368`（`_create_status_card`）
- Modify: `src/snoreguard/app.py`（`_init_tk_variables`, `on_osc_status_change`, `_update_osc_status_ui`, 新規 `_poll_vrc_status`, 各状態での `status_label` 色）
- Test: `tests/test_connection_state.py`

**Interfaces:**
- Produces:
  - `handler.derive_connection_state(last_rx: float | None, now: float, receiver_ok: bool, timeout_s: float = 120.0) -> str`（`"receiver_down" | "waiting" | "connected" | "stale"`）
  - `VRChatOSCReceiver.last_message_time: float | None`（`time.time()`、どのアドレスでも受信したら更新）
  - `VRCHandler.connection_state() -> str`
  - `SnoreGuardApp.vrc_status_var: tk.StringVar`、`SnoreGuardApp.vrc_status_label`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_connection_state.py`:

```python
from snoreguard.vrc.handler import derive_connection_state


def test_receiver_down_wins():
    assert derive_connection_state(10.0, 20.0, receiver_ok=False) == "receiver_down"


def test_waiting_until_first_message():
    assert derive_connection_state(None, 100.0, receiver_ok=True) == "waiting"


def test_connected_within_timeout():
    assert derive_connection_state(100.0, 150.0, receiver_ok=True) == "connected"


def test_stale_after_timeout():
    assert derive_connection_state(100.0, 300.0, receiver_ok=True, timeout_s=120) == "stale"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_connection_state.py -q`
Expected: ImportError

- [ ] **Step 3: handler.py を実装**

モジュール先頭に `import time` を追加し、関数を追加:

```python
def derive_connection_state(
    last_rx: float | None, now: float, receiver_ok: bool, timeout_s: float = 120.0
) -> str:
    """VRChat との接続状態を『受信実績』から導出する。

    UDP 送信は相手の有無に関係なく成功するため、送信できたことは接続の証拠に
    ならない。VRChat からのパラメータ受信（MuteSelf など）だけを根拠にする。
    """
    if not receiver_ok:
        return "receiver_down"
    if last_rx is None:
        return "waiting"
    return "connected" if now - last_rx <= timeout_s else "stale"
```

`VRChatOSCReceiver.__init__` に `self.last_message_time: float | None = None` を追加。`start()` の dispatcher 設定に `dispatcher_obj.set_default_handler(self._any_message_handler)` を追加し、メソッドを追加:

```python
    def _touch(self):
        self.last_message_time = time.time()

    def _any_message_handler(self, address: str, *args):
        """マップされていないアドレスの受信も『VRChat が生きている』証拠にする"""
        self._touch()
```

`_mute_handler`, `_toggle_detection_handler`, `_set_notification_handler`, `_set_auto_mute_handler` の先頭に `self._touch()` を追加。

`VRCHandler` に追加:

```python
    def connection_state(self) -> str:
        return derive_connection_state(
            self.osc_receiver.last_message_time,
            time.time(),
            receiver_ok=self.osc_receiver.is_running,
        )
```

- [ ] **Step 4: osc_query_service.py を「送信専用」に整理**

クラス docstring を `"""VRChat への OSC 送信クライアント（OSCQuery は未実装。名前は互換のため維持）"""` に変更。`_run_discovery` を以下に置き換え、`_monitor_connection` メソッドを削除:

```python
    def _run_discovery(self):
        """送信先（既定 127.0.0.1:9000）を設定する。接続確認はしない。"""
        try:
            self._establish_connection("127.0.0.1", 9000)
            self.log_callback("OSC: 送信先を 127.0.0.1:9000 に設定しました。", "system")
        except Exception as e:  # noqa: BLE001
            logger.error(f"OSC 送信クライアント初期化エラー: {e}", exc_info=True)
            self.log_callback(f"OSC: 送信クライアント初期化エラー: {e}", "error")
            self.status_callback(False, "OSC 初期化エラー")
```

`_establish_connection` の `self.status_callback(True, f"VRChat OSC接続 ({host}:{port})")` を `self.status_callback(True, f"OSC 送信先 {host}:{port}")` に（意味を正確に）。`_try_fallback_connection` は削除。

- [ ] **Step 5: UI と App**

`ui.py` `_create_status_card` の末尾（`app.status_label.grid(...)` の後）に追加:

```python
        app.vrc_status_label = ctk.CTkLabel(
            card,
            textvariable=app.vrc_status_var,
            font=self.font_s,
            text_color=self.COLOR_TEXT_2,
            anchor="w",
        )
        app.vrc_status_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
```

`app.py`:

- `_init_tk_variables` に `self.vrc_status_var = tk.StringVar(value="VRChat: 確認中")` を追加。
- `__init__` 末尾（`update_thread.start()` の前）に `self.root.after(3000, self._poll_vrc_status)` を追加。
- `_update_osc_status_ui` を削除し、`on_osc_status_change` を:

```python
    def on_osc_status_change(self, is_connected: bool, message: str):
        """OSC 送信クライアントの初期化結果（接続の証拠ではない）"""
        ThreadSafeHandler.safe_after(self.root, self.add_log, f"OSC: {message}", "osc")
        if is_connected and not hasattr(self, "_initial_feedback_sent"):
            ThreadSafeHandler.safe_after(self.root, self._send_delayed_feedback)
```

- 新規メソッド:

```python
    VRC_STATUS_TEXT = {
        "connected": ("VRChat: 接続中（パラメータ受信あり）", "#2ECC71"),
        "waiting": ("VRChat: 未確認（VRChat からの受信待ち）", "#F1C40F"),
        "stale": ("VRChat: 応答なし（2分以上受信なし）", "#E67E22"),
        "receiver_down": ("VRChat: 受信ポート 9001 が使用中", "#E74C3C"),
    }

    def _poll_vrc_status(self):
        """5 秒ごとに VRChat 接続状態を実測値から更新"""
        try:
            state = self.vrc_handler.connection_state()
            text, color = self.VRC_STATUS_TEXT.get(state, ("VRChat: 不明", "#96989d"))
            self.vrc_status_var.set(text)
            self.vrc_status_label.configure(text_color=color)
        except (AttributeError, tk.TclError):
            pass
        finally:
            self.root.after(5000, self._poll_vrc_status)

    def _set_detection_status(self, text: str, color: str = "#40444b"):
        """検出状態ラベルの文言と色をセットで更新する"""
        self.status_label_var.set(text)
        try:
            self.status_label.configure(fg_color=color)
        except (AttributeError, tk.TclError):
            pass
```

- 既存の `self.status_label_var.set(...)` のうち、状態遷移を表す箇所を `_set_detection_status` に置き換える: 「検出中」→ `("検出中", "#1F6AA5")`、「イビキ検出!」→ `("イビキ検出!", "#E67E22")`、「システム待機中」→ `("システム待機中", "#40444b")`、「初期化失敗」「音声入力エラー」→ 赤 `"#E74C3C"`、「🔊 検出中...」→ 青。`_warn_receiver_unavailable`（Phase 1）の `status_label` 色変更と文言は `vrc_status_var` 側に任せるため、`self.status_label.configure(...)` と `self.status_label_var.set("受信ポート 9001 が使用中")` の 2 行を削除する。

- [ ] **Step 6: テストと import スモーク、コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.ui; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/vrc/handler.py src/snoreguard/vrc/osc_query_service.py tests/test_connection_state.py
git commit -m "fix: VRChat 接続状態を受信実績から導出し、送信クライアント生成を接続扱いしない"
git add src/snoreguard/app.py src/snoreguard/ui.py
git commit -m "feat: VRChat 接続インジケータを検出状態ラベルから分離して常時表示"
```

---

### Task 16: 自動キャリブレーションの再設計

**Files:**
- Modify: `src/snoreguard/auto_calibrator.py`（`StageRecorder`, `FeatureAnalyzer`, `StatisticalCalibrator`, `AutoCalibrator`）
- Modify: `src/snoreguard/calibration_modal.py`（キャンセル、解析スレッド、音量ポーリング、サイズ）
- Test: `tests/test_calibrator.py`

**Interfaces:**
- Produces:
  - `auto_calibrator.CalibrationError(RuntimeError)`
  - `FeatureAnalyzer.analyze_audio(audio, label) -> AudioSample`（失敗時 `CalibrationError`。`features` は検出器と同じ frame/hop/pyin 範囲）
  - `StatisticalCalibrator.calculate_optimal_thresholds() -> CalibrationResult`（`CalibrationResult.warnings: list[str]` を追加）
  - `StageRecorder.latest_rms: float`（PortAudio コールバックが更新、UI はポーリング）、`StageRecorder.record_stage_async(...) -> bool`（停止要求時は completion_callback を呼ばず False）
  - `AutoCalibrator.analyze(audio, label) -> AudioSample`（ワーカースレッドから呼ぶ）、`AutoCalibrator.add_sample(sample)`
  - `CalibrationModal.MIN_CONFIDENCE_TO_APPLY = 0.5`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_calibrator.py`:

```python
import numpy as np
import pytest

from core.constants import HOP_LENGTH, SAMPLE_RATE
from snoreguard.auto_calibrator import (
    AudioSample,
    CalibrationError,
    FeatureAnalyzer,
    StatisticalCalibrator,
)


def _sample(label, rms, centroid, zcr, voiced, f0, n=400, jitter=0.0, seed=0):
    """フレームレベルの特徴量を持つ合成サンプル。jitter=1.0 で各特徴量に相対ノイズを乗せる。"""
    rng = np.random.default_rng(seed)
    noise = lambda scale: scale * jitter * rng.normal(size=n)  # noqa: E731
    feats = {
        "rms": np.abs(rms * (1 + noise(0.2))).astype(np.float32),
        "spectral_centroid": np.abs(centroid + noise(50)).astype(np.float32),
        "zcr": np.abs(zcr * (1 + noise(0.2))).astype(np.float32),
        "voiced_probs": np.clip(voiced + noise(0.05), 0, 1).astype(np.float32),
        "f0": np.abs(f0 + noise(5)).astype(np.float32) if f0 > 0 else np.zeros(n, np.float32),
    }
    return AudioSample(label=label, audio_data=np.zeros(1), features=feats, statistics={})


def _calibrator(conv_voiced=0.5):
    c = StatisticalCalibrator()
    c.add_sample(_sample("silence", 0.001, 800, 0.10, 0.02, 0.0, jitter=1.0, seed=1))
    c.add_sample(_sample("breathing", 0.006, 900, 0.12, 0.03, 0.0, jitter=1.0, seed=2))
    c.add_sample(_sample("snore", 0.04, 400, 0.03, 0.15, 95.0, jitter=1.0, seed=3))
    c.add_sample(_sample("conversation", 0.05, 1400, 0.09, conv_voiced, 180.0, jitter=1.0, seed=4))
    return c


def test_frame_level_statistics_are_not_degenerate():
    result = _calibrator().calculate_optimal_thresholds()
    fa = result.feature_analysis
    assert fa["rms"]["snore_std"] > 0
    assert fa["rms"]["snore_p25"] < fa["rms"]["snore_p75"]
    assert 0 < result.separation_quality["voiced_probs"] <= 1.0


def test_f0_confidence_threshold_stays_below_snore():
    # 会話の有声確率（0.5）がいびき（0.15）より高くても、閾値はいびきを通す
    result = _calibrator(conv_voiced=0.5).calculate_optimal_thresholds()
    thr = result.optimal_settings.f0_confidence_threshold
    assert thr < 0.15
    assert thr > 0.03


def test_thresholds_let_snore_pass_and_are_in_slider_range():
    s = _calibrator().calculate_optimal_thresholds().optimal_settings
    assert s.validate() == []
    assert s.energy_threshold < 0.04
    assert s.spectral_centroid_threshold > 400
    assert s.zcr_threshold > 0.03
    assert s.f0_min_hz < 95 < s.f0_max_hz


def test_silent_recording_produces_warnings_and_low_confidence():
    c = StatisticalCalibrator()
    for label in ("silence", "breathing", "snore", "conversation"):
        c.add_sample(_sample(label, 0.0, 0.0, 0.0, 0.0, 0.0))
    result = c.calculate_optimal_thresholds()
    assert result.warnings
    assert result.confidence_scores["total_confidence"] < 0.5
    assert result.optimal_settings.validate() == []


def test_feature_analyzer_matches_detector_frame_count():
    fa = FeatureAnalyzer()
    audio = np.random.default_rng(0).normal(0, 0.05, SAMPLE_RATE * 2).astype(np.float32)
    sample = fa.analyze_audio(audio, "breathing")
    assert len(sample.features["rms"]) == 1 + len(audio) // HOP_LENGTH
    assert set(sample.features) == {"rms", "spectral_centroid", "zcr", "f0", "voiced_probs"}


def test_feature_analyzer_raises_on_empty_audio():
    with pytest.raises(CalibrationError):
        FeatureAnalyzer().analyze_audio(np.zeros(0, dtype=np.float32), "snore")
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_calibrator.py -q`
Expected: ImportError（`CalibrationError` なし）

- [ ] **Step 3: auto_calibrator.py を実装**

import を `from core.constants import BANDPASS_HZ, FRAME_LENGTH, HOP_LENGTH, SAMPLE_RATE` と `from core.rule_processor import FeatureExtractionError, FeatureExtractor` と `from core.settings import SLIDER_RANGES, RuleSettings` に整理し、`librosa` の import は削除する。

`CalibrationResult` に `warnings: list[str] = field(default_factory=list)` を追加（`from dataclasses import dataclass, field`）。追加:

```python
class CalibrationError(RuntimeError):
    """キャリブレーションの録音/解析が使えない（再試行を促す）"""
```

`StageRecorder`:
- `__init__` に `self.latest_rms = 0.0` と `self._stop_requested = False` を追加。
- `_audio_callback` を以下に（**Tk を呼ばない**。音量は属性に置くだけ）:

```python
    def _audio_callback(self, indata, frames, time, status):
        """PortAudio スレッド。UI は呼ばず、バッファ追加と音量の記録のみ行う"""
        if status:
            logger.warning(f"録音ステータス: {status}")
        if self.is_recording:
            self.audio_chunk_buffer.append(indata.copy())
            self.latest_rms = float(np.sqrt(np.mean(indata**2)))
```

- `set_callbacks` から `volume_callback` を削除（引数は残してよいが未使用）。
- `record_stage_async` のループ後、`self.is_recording = False` の直後に追加:

```python
            if self._stop_requested:
                logger.info("停止要求により録音を破棄")
                return False
```

`stop_recording` を `self._stop_requested = True; self.is_recording = False` に、`record_stage_async` 冒頭で `self._stop_requested = False` に初期化。

`FeatureAnalyzer` を以下に置き換える:

```python
class FeatureAnalyzer:
    """録音全体の特徴量を、検出器と同一のパラメータで計算する"""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.sos_filter = butter(
            N=5, Wn=list(BANDPASS_HZ), btype="bandpass", fs=sample_rate, output="sos"
        )
        # 設定は pyin に影響しないため既定値でよい（探索範囲は core.constants）
        self.extractor = FeatureExtractor(sample_rate, FRAME_LENGTH, HOP_LENGTH, RuleSettings())

    def analyze_audio(self, audio_data: np.ndarray, label: str) -> AudioSample:
        if audio_data is None or len(audio_data) < FRAME_LENGTH:
            raise CalibrationError("録音が短すぎます")
        try:
            filtered_audio = sosfilt(self.sos_filter, audio_data).astype(np.float32)
            features = self.extractor.extract_features(filtered_audio)
        except FeatureExtractionError as e:
            raise CalibrationError(f"特徴量の計算に失敗しました: {e}") from e
        statistics = self._calculate_statistics_with_outlier_removal(features)
        return AudioSample(
            label=label, audio_data=filtered_audio, features=features, statistics=statistics
        )
```

（`_calculate_statistics_with_outlier_removal` は既存のまま残す。）

`StatisticalCalibrator`:
- `_analyze_feature_distributions` を**フレーム分布**に:

```python
    def _frames(self, feature: str, label: str) -> np.ndarray:
        """ラベルの全サンプルのフレーム値を連結（無効値は除外）"""
        chunks = [s.features.get(feature) for s in self.samples if s.label == label]
        chunks = [c for c in chunks if c is not None and len(c) > 0]
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        values = np.concatenate(chunks).astype(np.float32)
        values = values[~np.isnan(values)]
        if feature in ("f0", "rms"):
            values = values[values > 1e-6]
        return values

    def _analyze_feature_distributions(self) -> Dict[str, Dict[str, float]]:
        feature_analysis: Dict[str, Dict[str, float]] = {}
        for feature in ["rms", "spectral_centroid", "zcr", "voiced_probs", "f0"]:
            feature_analysis[feature] = {}
            for label in ["silence", "breathing", "snore", "conversation"]:
                values = self._frames(feature, label)
                if len(values) == 0:
                    continue
                feature_analysis[feature][f"{label}_mean"] = float(np.mean(values))
                feature_analysis[feature][f"{label}_std"] = float(np.std(values))
                for p in (10, 25, 75, 90):
                    feature_analysis[feature][f"{label}_p{p}"] = float(np.percentile(values, p))
        return feature_analysis
```

- `_calculate_thresholds` を方向付き・クランプ付きに:

```python
    def _calculate_thresholds(self, fa: Dict) -> RuleSettings:
        """各特徴量について『いびきが必ず通る側』に閾値を置く"""
        s = RuleSettings()
        rms, cen, zcr, vp, f0 = (fa.get(k, {}) for k in ("rms", "spectral_centroid", "zcr", "voiced_probs", "f0"))

        # エネルギー（下限）: 呼吸の上側といびきの下側の中点。いびき p25 の 90% を超えない。
        if "snore_p25" in rms:
            noise = max(rms.get("silence_p75", 0.0) * 1.5, rms.get("breathing_p75", 0.0))
            thr = (noise + rms["snore_p25"]) / 2
            s.energy_threshold = max(0.005, min(thr, rms["snore_p25"] * 0.9))

        # スペクトル重心（上限）: いびき p75 と会話 p25 の中点。いびき p75 の 110% を下回らない。
        if "snore_p75" in cen:
            other = cen.get("conversation_p25", cen["snore_p75"] * 1.5)
            thr = (cen["snore_p75"] + other) / 2
            s.spectral_centroid_threshold = max(thr, cen["snore_p75"] * 1.1)

        # ZCR（上限）: 同上
        if "snore_p75" in zcr:
            other = zcr.get("conversation_p25", zcr["snore_p75"] * 1.5)
            thr = (zcr["snore_p75"] + other) / 2
            s.zcr_threshold = max(thr, zcr["snore_p75"] * 1.1)

        # F0 信頼度（下限）: いびき p25 と呼吸 p75 の中点。会話は比較対象にしない。
        if "snore_p25" in vp:
            thr = (vp["snore_p25"] + vp.get("breathing_p75", 0.0)) / 2
            s.f0_confidence_threshold = min(thr, vp["snore_p25"] * 0.9)

        # F0 範囲: いびきの p10〜p90 に余裕を持たせる
        if "snore_p10" in f0 and f0.get("snore_mean", 0) > 0:
            s.f0_min_hz = f0["snore_p10"] - 10.0
            s.f0_max_hz = f0["snore_p90"] + 10.0

        return s.sanitized()
```

- `_evaluate_separation_quality` をフレーム分布の d' に:

```python
    def _evaluate_separation_quality(self) -> Dict[str, float]:
        quality = {}
        for feature in ["rms", "spectral_centroid", "zcr", "voiced_probs"]:
            snore = self._frames(feature, "snore")
            if len(snore) < 2:
                continue
            separations = []
            for opponent in ("breathing", "conversation"):
                other = self._frames(feature, opponent)
                if len(other) < 2:
                    continue
                pooled = np.sqrt((np.var(snore) + np.var(other)) / 2) + 1e-9
                d_prime = abs(float(np.mean(snore)) - float(np.mean(other))) / pooled
                separations.append(min(1.0, d_prime / 3.0))
            if separations:
                quality[feature] = float(np.mean(separations))
        return quality
```

- `calculate_optimal_thresholds` の末尾で警告を付与:

```python
        warnings = []
        snore_rms = self._frames("rms", "snore")
        if len(snore_rms) == 0 or float(np.mean(snore_rms)) < 1e-3:
            warnings.append("いびき音がほとんど録音されていません（音量が小さすぎます）")
        for label in ("breathing", "conversation"):
            if len(self._frames("rms", label)) == 0:
                warnings.append(f"{label} の録音が無音でした")
        if confidence_scores["total_confidence"] < 0.5:
            warnings.append("信頼度が低いため、静かな環境で再試行することを推奨します")
        return CalibrationResult(..., warnings=warnings)
```

`_calculate_confidence_scores` の `signal_quality` は `self._frames("rms", "snore")` の平均を使う（空なら 0.0）。`overall_separation` は `separation_quality` が空のとき **0.0**（旧実装の 0.5 は「何も測れていない」状態を中程度の信頼度に見せてしまう）。

`AutoCalibrator`:
- `process_recorded_audio` を削除し、次を追加:

```python
    def analyze(self, audio_data: np.ndarray, label: str) -> AudioSample:
        """録音データを解析する（ワーカースレッドから呼ぶ。失敗は CalibrationError）"""
        return self.analyzer.analyze_audio(audio_data, label)

    def add_sample(self, sample: AudioSample) -> None:
        self.calibrator.add_sample(sample)
```

- [ ] **Step 4: calibration_modal.py をキャンセル可能・非ブロッキングに**

- `__init__` に `self._after_ids: list[str] = []`、`self.MIN_CONFIDENCE_TO_APPLY = 0.5`。
- ヘルパー:

```python
    def _after(self, ms: int, func, *args):
        """after の ID を記録して stop/close で一括キャンセルできるようにする"""
        if not self.modal_window:
            return
        self._after_ids.append(self.modal_window.after(ms, func, *args))

    def _cancel_afters(self):
        for after_id in self._after_ids:
            try:
                self.modal_window.after_cancel(after_id)
            except Exception:  # noqa: BLE001
                pass
        self._after_ids.clear()

    def _is_active(self) -> bool:
        return bool(self.modal_window and self.auto_calibrator and self.auto_calibrator.is_calibrating)
```

- `stop_calibration`: `self.auto_calibrator.stop_calibration(); self._cancel_afters(); self._reset_ui(); self.status_var.set("停止しました")`。`close`: `stop_calibration` 相当の後に destroy。
- `_start_stage` の先頭に `if not self._is_active(): return`、`self.modal_window.after(3000, ...)` を `self._after(3000, self._start_recording, stage_name, duration)` に。
- `_start_recording` を以下に（解析も録音スレッドで行う）:

```python
    def _start_recording(self, stage_name: str, duration: float):
        if not self._is_active():
            return
        import threading

        _, _, _, label = self.auto_calibrator.get_stage_info(self.current_stage)
        self._after(100, self._poll_volume)

        def record_thread():
            recorder = self.auto_calibrator.recorder
            ok = recorder.record_stage_async(stage_name, duration)
            if not ok:
                if self._is_active():
                    self.modal_window.after(0, self._on_stage_failed, "録音に失敗しました")
                return
            audio = recorder.last_audio
            try:
                sample = self.auto_calibrator.analyze(audio, label)
            except Exception as e:  # noqa: BLE001 - UI に伝える
                self.modal_window.after(0, self._on_stage_failed, f"解析に失敗: {e}")
                return
            rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
            self.modal_window.after(0, self._on_sample_ready, sample, rms)

        threading.Thread(target=record_thread, daemon=True, name="calibration-record").start()

    def _poll_volume(self):
        """PortAudio スレッドが書いた最新 RMS を 100ms ごとに読む（Tk は主スレッドのみ）"""
        if not self._is_active():
            return
        self.volume_bar.set(min(self.auto_calibrator.recorder.latest_rms * 50, 1.0))
        self._after(100, self._poll_volume)

    def _on_sample_ready(self, sample, rms_level: float):
        if not self._is_active():
            return
        self.auto_calibrator.add_sample(sample)
        self.status_var.set(f"ステージ {self.current_stage + 1} 完了 (RMS: {rms_level:.4f})")
        if rms_level < 1e-3 and sample.label != "silence":
            self.status_var.set("音声が検出されませんでした。マイクを確認して再試行してください")
            self.stop_calibration()
            return
        self.current_stage += 1
        self._after(2000, self._start_stage)

    def _on_stage_failed(self, message: str):
        self.status_var.set(message)
        self.stop_calibration()
```

`StageRecorder.record_stage_async` は `self.last_audio = audio_data` を保持する（`__init__` で `self.last_audio = np.zeros(0, dtype=np.float32)`）。`completion_callback` は呼ばなくてよい（モーダルが `last_audio` を読む）。`_on_progress` / `_update_progress` はそのまま（録音ループのスレッドから `after`）。`_on_volume`/`_update_volume`/`_on_stage_completion`/`_process_completion` は削除。`import numpy as np` を追加。

- `_complete_calibration` で信頼度ゲート: 結果表示後、`confidence >= self.MIN_CONFIDENCE_TO_APPLY` のときだけ `apply_button.grid(...)`、そうでなければ `self.status_var.set(f"信頼度 {confidence:.0%} が低いため適用できません。静かな環境で再試行してください")`。警告は `result_text` の先頭に `"注意: " + "\n注意: ".join(result.warnings)` で表示する（`_display_calibration_changes` に追記）。
- ウィンドウ高さ: `show()` の `geometry("500x600")` を `f"500x{min(600, self.parent.winfo_screenheight() - 120)}"` に、`_complete_calibration` の `geometry("500x800")` を `f"500x{min(800, self.parent.winfo_screenheight() - 120)}"` に。`_create_widgets` の `main_frame` を `ctk.CTkScrollableFrame(self.modal_window, fg_color="transparent")` にする（`grid_columnconfigure(0, weight=1)` はそのまま）。

- [ ] **Step 5: テストと import スモーク、コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.calibration_modal; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/auto_calibrator.py tests/test_calibrator.py
git commit -m "fix: キャリブレーションを検出器と同じ特徴量で計算し、フレーム分布と方向付き閾値で統計を取り直す"
git add src/snoreguard/calibration_modal.py
git commit -m "fix: キャリブレーションの停止を即時反映し、解析をワーカースレッドで行い、信頼度の低い結果は適用不可にする"
```

---

### Task 17: スレッド境界の規律（queue 経由の通知・非ブロッキング停止・OSC 委譲）

**Files:**
- Modify: `src/snoreguard/audio_service.py`（`__init__`, `start`, `stop`, `_process_stream_data`, 新規 `_emit_log`）
- Modify: `src/snoreguard/app.py`（`__init__` の `event_queue`/`_pump_events`、`_on_closing`、OSC 用 `handle_osc_*`、`run_on_ui_thread`）
- Modify: `src/snoreguard/vrc/handler.py`（`_DaemonThreadingOSCUDPServer`、ハンドラの委譲）
- Test: `tests/test_audio_service_threading.py`, `tests/test_osc_server_daemon.py`

**Interfaces:**
- Produces:
  - `AudioService.__init__(..., event_queue: queue.Queue | None = None)`。ワーカー内のログは `("log", message, level)` を `event_queue` に積む（無ければ `log_callback`）。
  - `AudioService.stop()` は **join しない**（フラグを落とすだけ）。`AudioService.start()` は前回のワーカーが生きていれば最大 2 秒待ち、残っていれば `RuntimeError`。
  - `SnoreGuardApp.event_queue: queue.Queue`、`SnoreGuardApp.run_on_ui_thread(func, *args)`、`SnoreGuardApp.handle_osc_toggle_detection(value: bool)`, `handle_osc_set_notification(value: bool)`, `handle_osc_set_auto_mute(value: bool)`（メインスレッドで実行される）
  - `handler._DaemonThreadingOSCUDPServer(osc_server.ThreadingOSCUDPServer)`: `daemon_threads = True`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_audio_service_threading.py`:

```python
import queue
import threading
import time

import numpy as np
import pytest

import snoreguard.audio_service as audio_service_module
from core.settings import RuleSettings
from snoreguard.audio_service import AudioService


class _SlowStream:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, frames):
        time.sleep(0.05)
        return np.zeros((frames, 1), dtype=np.float32), True  # overflowed=True


@pytest.fixture
def fake_sd(monkeypatch):
    monkeypatch.setattr(audio_service_module.sd, "InputStream", _SlowStream)
    monkeypatch.setattr(
        audio_service_module.sd, "query_devices", lambda: [{"name": "f", "max_input_channels": 1}]
    )


def test_stop_does_not_block_caller(fake_sd):
    done = threading.Event()
    svc = AudioService(
        RuleSettings(),
        queue.Queue(maxsize=5),
        snore_detected_callback=lambda: None,
        log_callback=lambda m, level="info": None,
        on_stream_stopped=lambda e: done.set(),
        event_queue=queue.Queue(),
    )
    svc.start(0)
    time.sleep(0.2)
    t0 = time.perf_counter()
    svc.stop()
    assert time.perf_counter() - t0 < 0.2
    assert done.wait(timeout=3)


def test_worker_logs_go_to_event_queue(fake_sd):
    events = queue.Queue()
    done = threading.Event()
    svc = AudioService(
        RuleSettings(),
        queue.Queue(maxsize=5),
        snore_detected_callback=lambda: None,
        log_callback=lambda m, level="info": pytest.fail("ワーカーから log_callback を直接呼んではいけない"),
        on_stream_stopped=lambda e: done.set(),
        event_queue=events,
    )
    svc.start(0)
    time.sleep(0.3)
    svc.stop()
    done.wait(timeout=3)
    kinds = [events.get_nowait()[0] for _ in range(events.qsize())]
    assert "log" in kinds
```

`tests/test_osc_server_daemon.py`:

```python
from snoreguard.vrc.handler import _DaemonThreadingOSCUDPServer


def test_handler_threads_are_daemon():
    assert _DaemonThreadingOSCUDPServer.daemon_threads is True
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_audio_service_threading.py tests/test_osc_server_daemon.py -q`
Expected: TypeError（`event_queue` なし）/ ImportError

- [ ] **Step 3: AudioService**

- `__init__` に `event_queue: queue.Queue | None = None` を追加し `self.event_queue = event_queue`、`self._last_overflow_log = 0.0`（`import time`, `import queue` を追加）。
- 追加:

```python
    def _emit_log(self, message: str, level: str = "info"):
        """ワーカースレッドからのログ。Tk を呼ばず、キューに積むだけ。"""
        if self.event_queue is not None:
            self.event_queue.put(("log", message, level))
        else:
            self.log_callback(message, level)
```

- `_detection_loop` 内の `self.log_callback("オーディオストリームを開始しました。", "system")` を `self._emit_log(...)` に。`_process_stream_data` のオーバーフロー警告を:

```python
        if overflowed:
            logger.warning("オーディオバッファオーバーフロー")
            now = time.monotonic()
            if now - self._last_overflow_log > 10.0:  # 10 秒に 1 回だけ UI に出す
                self._last_overflow_log = now
                self._emit_log("オーディオバッファがオーバーフローしました。", "warning")
```

- `start()`: `if self.is_running: ... return` の後に:

```python
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)  # 前回のワーカーの終了を待つ（Tk は呼ばれないのでデッドロックしない）
            if self._thread.is_alive():
                raise RuntimeError("前回の音声スレッドがまだ終了していません")
```

- `stop()` を以下に:

```python
    def stop(self):
        """停止を要求する（ワーカーの終了は on_stream_stopped で通知される）"""
        logger.debug("AudioService停止要求")
        self.is_running = False
        self._clear_buffers()
        logger.info("AudioService停止要求完了")
```

（`join(timeout=1.0)` と `self._thread = None` は削除。`_thread` はワーカー終了後も参照を残し、`start()` で待ち合わせに使う。）

- [ ] **Step 4: handler.py**

追加:

```python
class _DaemonThreadingOSCUDPServer(osc_server.ThreadingOSCUDPServer):
    """終了時にハンドラスレッドがプロセスを引き留めないようデーモン化"""

    daemon_threads = True
```

`start()` の `osc_server.ThreadingOSCUDPServer(...)` を `_DaemonThreadingOSCUDPServer(...)` に。3 つのハンドラを委譲のみに:

```python
    def _toggle_detection_handler(self, address: str, value):
        self._touch()
        if self.app_instance:
            self.app_instance.run_on_ui_thread(
                self.app_instance.handle_osc_toggle_detection, address, bool(value)
            )

    def _set_notification_handler(self, address: str, value):
        self._touch()
        if self.app_instance:
            self.app_instance.run_on_ui_thread(
                self.app_instance.handle_osc_set_notification, address, bool(value)
            )

    def _set_auto_mute_handler(self, address: str, value):
        self._touch()
        if self.app_instance:
            self.app_instance.run_on_ui_thread(
                self.app_instance.handle_osc_set_auto_mute, address, bool(value)
            )
```

（ログ出力は App 側の `handle_osc_*` で行う。）

- [ ] **Step 5: app.py**

- `__init__`: `self.event_queue = queue.Queue()` を `data_queue` の直後に。`AudioService(...)` に `event_queue=self.event_queue` を追加。`__init__` 末尾に `self.root.after(100, self._pump_events)`。
- 音声ワーカーからの **停止通知と検出通知も queue 経由**にする（ワーカーが `root.after` でメインスレッドを待たないようにするため。これで `AudioService.start()` の `join(2.0)` がデッドロックしない）。Phase 1 の 2 メソッドを次に置き換える:

```python
    def _on_audio_stream_stopped(self, error: str | None):
        """音声ワーカー終了通知（ワーカースレッドから呼ばれる。Tk は触らない）"""
        self.event_queue.put(("stopped", error))

    def on_snore_detected_callback(self):
        """いびき検出コールバック（ワーカースレッドから呼ばれる。Tk は触らない）"""
        self.event_queue.put(("snore",))
```

- 追加:

```python
    def run_on_ui_thread(self, func, *args):
        """他スレッドからメインスレッドへ処理を委譲する唯一の入口"""
        ThreadSafeHandler.safe_after(self.root, func, *args)

    def _pump_events(self):
        """ワーカーからのイベント（ログ・停止・検出）をメインスレッドで排出"""
        try:
            while True:
                kind, *payload = self.event_queue.get_nowait()
                if kind == "log":
                    self.add_log(payload[0], payload[1])
                elif kind == "stopped":
                    self._handle_stream_stopped(payload[0])
                elif kind == "snore":
                    self._handle_detection_event()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._pump_events)

    def handle_osc_toggle_detection(self, address: str, value: bool):
        self.add_log(f"VRChatから検出{'開始' if value else '停止'}通知: {value} 🎵", "vrchat")
        if value and not self.is_running:
            self._start_detection(origin="osc")
        elif not value and self.is_running:
            self._stop_detection()

    def handle_osc_set_notification(self, address: str, value: bool):
        self.add_log(f"VRChatから通知{'ON' if value else 'OFF'}通知 🔔", "vrchat")
        self.set_notification_from_osc(value)

    def handle_osc_set_auto_mute(self, address: str, value: bool):
        self.add_log(f"VRChatから自動ミュート{'ON' if value else 'OFF'}通知 🔇", "vrchat")
        self.set_auto_mute_from_osc(value)
```

- `_on_closing` を以下に（メインスレッドでの join を避ける）:

```python
    def _on_closing(self):
        """終了処理。ワーカーの join はせず、停止要求→設定保存→破棄の順で進める"""
        if getattr(self, "_closing", False):
            return
        self._closing = True
        logger.debug("アプリケーション終了処理開始")
        if self.is_running or self.is_initializing:
            self._stop_detection()
        self.time_scheduler.stop()
        self._save_app_settings(send_feedback=False)
        self.vrc_handler.stop()
        self.root.destroy()
        logger.debug("アプリケーション終了処理完了")
```

- [ ] **Step 6: テストと import スモーク、コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/audio_service.py tests/test_audio_service_threading.py
git commit -m "fix: 音声ワーカーの通知を queue 経由にし、停止でメインスレッドを join させない"
git add src/snoreguard/vrc/handler.py src/snoreguard/app.py tests/test_osc_server_daemon.py
git commit -m "fix: OSC ハンドラをメインスレッドへの委譲のみにし、ハンドラスレッドをデーモン化"
```

---

### Task 18: VRChat からのパラメータ再送（エコー）の判別と /avatar/change

**Files:**
- Create: `src/snoreguard/vrc/echo_filter.py`
- Modify: `src/snoreguard/vrc/handler.py`（`VRCHandler.__init__/send_feedback`、受信側 `/avatar/change`）
- Modify: `src/snoreguard/app.py`（`handle_osc_*` でのエコー判定、`handle_avatar_change`、OSC 経由変更の非永続化）
- Test: `tests/test_echo_filter.py`

**Interfaces:**
- Produces:
  - `echo_filter.OscEchoFilter(suppress_seconds: float = 2.0, clock=time.monotonic)` with `record_sent(address, value)`, `suppress_inputs()`, `should_apply(address, value) -> bool`
  - `VRCHandler.echo_filter: OscEchoFilter`
  - `SnoreGuardApp.handle_avatar_change(avatar_id: str)`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_echo_filter.py`:

```python
from snoreguard.vrc.echo_filter import OscEchoFilter


def _f():
    now = [100.0]
    f = OscEchoFilter(suppress_seconds=2.0, clock=lambda: now[0])
    return f, now


def test_echo_of_last_sent_value_is_ignored():
    f, _ = _f()
    f.record_sent("/avatar/parameters/SnoreGuard/SetAutoMute", True)
    assert f.should_apply("/avatar/parameters/SnoreGuard/SetAutoMute", True) is False
    assert f.should_apply("/avatar/parameters/SnoreGuard/SetAutoMute", False) is True


def test_unknown_address_is_applied():
    f, _ = _f()
    assert f.should_apply("/avatar/parameters/SnoreGuard/ToggleDetection", True) is True


def test_inputs_are_suppressed_after_avatar_change():
    f, now = _f()
    f.suppress_inputs()
    assert f.should_apply("/avatar/parameters/SnoreGuard/ToggleDetection", False) is False
    now[0] += 2.5
    assert f.should_apply("/avatar/parameters/SnoreGuard/ToggleDetection", False) is True
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_echo_filter.py -q`
Expected: ImportError

- [ ] **Step 3: 実装**

`src/snoreguard/vrc/echo_filter.py`:

```python
"""VRChat から届くパラメータが『利用者の操作』か『再送（エコー）』かを判別する。

VRChat はアバターのロード/変更時に全パラメータの現在値を再送する。これを
操作として扱うと、SnoreGuard 側の設定や検出状態がアバター既定値で上書きされる。
"""

import time
from collections.abc import Callable


class OscEchoFilter:
    def __init__(self, suppress_seconds: float = 2.0, clock: Callable[[], float] = time.monotonic):
        self.suppress_seconds = suppress_seconds
        self.clock = clock
        self._last_sent: dict[str, object] = {}
        self._suppress_until = 0.0

    def record_sent(self, address: str, value) -> None:
        self._last_sent[address] = value

    def suppress_inputs(self) -> None:
        """アバター変更直後の再送を一定時間無視する"""
        self._suppress_until = self.clock() + self.suppress_seconds

    def should_apply(self, address: str, value) -> bool:
        if self.clock() < self._suppress_until:
            return False
        return self._last_sent.get(address, _MISSING) != value


_MISSING = object()
```

`handler.py`: `from snoreguard.vrc.echo_filter import OscEchoFilter`。`VRCHandler.__init__` に `self.echo_filter = OscEchoFilter()`。`send_feedback` で送信成功後に `self.echo_filter.record_sent(address, value)`。受信側 `start()` に `dispatcher_obj.map("/avatar/change", self._avatar_change_handler)` と:

```python
    def _avatar_change_handler(self, address: str, avatar_id=""):
        self._touch()
        if self.app_instance:
            self.app_instance.run_on_ui_thread(self.app_instance.handle_avatar_change, str(avatar_id))
```

`app.py`:

```python
    def handle_avatar_change(self, avatar_id: str):
        """アバター変更: 再送される既定値を無視し、SnoreGuard 側の状態を VRChat へ再プッシュ"""
        self.add_log("VRChat のアバター変更を検知。状態を再送信します。", "vrchat")
        self.vrc_handler.echo_filter.suppress_inputs()
        self.root.after(1500, self._send_status_feedback)
```

`handle_osc_toggle_detection` / `handle_osc_set_notification` / `handle_osc_set_auto_mute` の先頭に:

```python
        if not self.vrc_handler.echo_filter.should_apply(address, value):
            logger.debug(f"OSC エコーを無視: {address}={value}")
            return
```

`set_notification_from_osc` / `set_auto_mute_from_osc` から `self._save_app_settings(...)` 呼び出しを削除（OSC 経由の変更はセッション内のみ。永続化は UI 操作と終了時の保存に任せる）。

- [ ] **Step 4: テストと import スモーク、コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/vrc/echo_filter.py src/snoreguard/vrc/handler.py src/snoreguard/app.py tests/test_echo_filter.py
git commit -m "fix: VRChat からのパラメータ再送を操作と区別し、アバター変更時は SnoreGuard 側の状態を再送信する"
```

---

### Task 19: mDNS の硬化（ポインタ検証・ループバック限定・SRV ポートの活用）

**Files:**
- Modify: `src/snoreguard/vrc/mdns_client.py`（`_parse_name`, `_process_service_records`, `_listen_loop`）
- Modify: `src/snoreguard/vrc/handler.py`（`on_vrchat_discovered`）
- Test: `tests/test_mdns_parse.py`

**Interfaces:**
- Produces:
  - `MDNSClient._parse_name(data, offset) -> tuple[str, int]`：圧縮ポインタは **後方のみ**・最大 16 回・再訪禁止。違反は `ValueError`。
  - コールバック引数 `{"ip_addresses": [src_ip], "oscquery_port": int, "osc_port": int | None}`（TXT の `osc-port` は任意）
  - `VRCHandler.on_vrchat_discovered(service_info)`: `ip_addresses[0]` が `127.` 始まりでなければログだけで無視。`self.oscquery_http_port` を保持。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_mdns_parse.py`:

```python
import struct
import threading

import pytest

from snoreguard.vrc.mdns_client import MDNSClient


def _name(labels):
    out = b""
    for part in labels:
        out += struct.pack("!B", len(part)) + part.encode()
    return out + b"\x00"


def test_parse_plain_name():
    client = MDNSClient()
    data = b"\x00" * 12 + _name(["_oscjson", "_tcp", "local"])
    name, offset = client._parse_name(data, 12)
    assert name == "_oscjson._tcp.local"
    assert offset == len(data)


def test_self_referencing_pointer_raises_quickly():
    client = MDNSClient()
    data = b"\x00" * 12 + b"\xc0\x0c"  # offset 12 が自分自身を指す
    result = {}

    def run():
        try:
            client._parse_name(data, 12)
        except ValueError:
            result["raised"] = True

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=1.0)
    assert not t.is_alive()
    assert result.get("raised") is True


def test_forward_pointer_is_rejected():
    client = MDNSClient()
    data = b"\x00" * 12 + b"\xc0\x10" + b"\x00\x00" + _name(["a"])
    with pytest.raises(ValueError):
        client._parse_name(data, 12)


def test_backward_pointer_is_followed():
    client = MDNSClient()
    base = b"\x00" * 12 + _name(["_tcp", "local"])
    data = base + b"\x03abc" + b"\xc0\x0c"  # "abc" + pointer → "abc._tcp.local"
    name, offset = client._parse_name(data, len(base))
    assert name == "abc._tcp.local"
    assert offset == len(data)


def test_service_callback_uses_srv_port_without_txt():
    received = []
    client = MDNSClient(service_callback=received.append)
    instance = _name(["VRChat-Client-ABC", "_oscjson", "_tcp", "local"])
    header = struct.pack("!HHHHHH", 0, 0x8400, 0, 2, 0, 0)
    ptr_rr = _name(["_oscjson", "_tcp", "local"]) + struct.pack("!HHIH", 12, 1, 120, len(instance)) + instance
    srv_data = struct.pack("!HHH", 0, 0, 9012) + _name(["host", "local"])
    srv_rr = instance + struct.pack("!HHIH", 33, 1, 120, len(srv_data)) + srv_data
    client._parse_mdns_response(header + ptr_rr + srv_rr, "127.0.0.1")
    assert received and received[0]["oscquery_port"] == 9012
    assert received[0]["ip_addresses"] == ["127.0.0.1"]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_mdns_parse.py -q`
Expected: `test_self_referencing_pointer_raises_quickly` と `test_forward_pointer_is_rejected` と `test_service_callback_uses_srv_port_without_txt` が FAIL

- [ ] **Step 3: 実装**

`_parse_name` を以下に置き換える:

```python
    MAX_POINTER_JUMPS = 16

    def _parse_name(self, data: bytes, offset: int) -> tuple[str, int]:
        """DNS 名を解析する。

        圧縮ポインタ（上位 2 ビット = 11）は RFC 1035 どおり『自分より前』のみ許可し、
        ジャンプ回数と再訪を制限する。違反は ValueError（パケットごと破棄）。
        """
        parts = []
        end_offset = None  # 最初のポインタの直後（呼び出し側が読み進める位置）
        jumps = 0
        visited: set[int] = set()

        while True:
            if offset >= len(data):
                raise ValueError("名前が途中で終わっています")
            length = data[offset]
            if length == 0:
                offset += 1
                break
            if length & 0xC0 == 0xC0:
                if offset + 1 >= len(data):
                    raise ValueError("圧縮ポインタが途中で終わっています")
                pointer = struct.unpack("!H", data[offset : offset + 2])[0] & 0x3FFF
                if pointer >= offset or pointer in visited:
                    raise ValueError(f"不正な圧縮ポインタ: {pointer} (現在位置 {offset})")
                jumps += 1
                if jumps > self.MAX_POINTER_JUMPS:
                    raise ValueError("圧縮ポインタのジャンプ回数が上限を超えました")
                visited.add(offset)
                if end_offset is None:
                    end_offset = offset + 2
                offset = pointer
                continue
            if length & 0xC0:
                raise ValueError("未対応のラベル種別")
            offset += 1
            if offset + length > len(data):
                raise ValueError("ラベルがパケット長を超えています")
            parts.append(data[offset : offset + length].decode("ascii", errors="ignore"))
            offset += length

        return ".".join(parts), (end_offset if end_offset is not None else offset)
```

`_parse_resource_record` の `except Exception: return None, offset` はそのまま（ValueError を握ってレコードを捨てる）。ただし `_parse_mdns_response` 内の Question スキップで `_parse_name` が ValueError を出した場合も既存の外側 `except Exception: pass` で破棄される。

`_process_service_records` の段階 3〜4 を以下に置き換える（TXT は任意、SRV 必須）:

```python
        # 段階3: TXT（任意）。VRChat は osc-port を広告しないため存在しなくてよい
        for record in records:
            if record.rtype == self.TYPE_TXT and record.name in oscquery_services:
                try:
                    txt_data = self._parse_txt_record(record.data)
                    if "osc-port" in txt_data:
                        oscquery_services[record.name]["osc_port"] = int(txt_data["osc-port"])
                except Exception:  # noqa: BLE001
                    continue

        # 段階4: SRV（OSCQuery の HTTP ポート）が揃ったサービスを通知（最新を優先）
        for service_name, service_info in oscquery_services.items():
            if "port" not in service_info:
                continue
            callback_info = {
                "ip_addresses": [src_ip],
                "oscquery_port": service_info["port"],
                "osc_port": service_info.get("osc_port"),
            }
            if self.discovered_services.get(service_name) == callback_info:
                continue  # 変化なし
            self.discovered_services[service_name] = callback_info
            if self.service_callback:
                self.service_callback(callback_info)
```

`_listen_loop` の `except Exception:` を:

```python
            except OSError:
                if self.running:
                    time.sleep(0.1)
                else:
                    break  # stop() でソケットが閉じられた
```

`handler.py` の `VRCHandler.__init__` に `self.oscquery_http_port: int | None = None`。`on_vrchat_discovered` を以下に:

```python
    def on_vrchat_discovered(self, service_info):
        """mDNS で OSCQuery サービスを発見。ループバック以外は採用しない。"""
        host = service_info["ip_addresses"][0] if service_info.get("ip_addresses") else ""
        if not host.startswith("127."):
            logger.warning(f"ループバック以外からの OSCQuery 広告を無視: {host}")
            return
        self.oscquery_http_port = service_info.get("oscquery_port")
        logger.info(f"VRChat OSCQuery を検出: http://{host}:{self.oscquery_http_port}")
        self.log_callback(f"OSCQuery 検出: {host}:{self.oscquery_http_port}", "osc")
        osc_port = service_info.get("osc_port")
        if osc_port and osc_port != self.osc_service.vrchat_osc_port:
            self._update_osc_service_connection(host, osc_port)
            self.log_callback(f"OSC 送信先を更新: {host}:{osc_port}", "osc")
```

`mdns_client.py` の `_on_service_discovered` のログ文言を `f"OSCQuery発見: {ip}:{service_info.get('oscquery_port', 'N/A')}"` に。

- [ ] **Step 4: テストとコミット**

Run: `uv run --no-sync pytest -q`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/vrc/mdns_client.py src/snoreguard/vrc/handler.py tests/test_mdns_parse.py
git commit -m "fix: mDNS の圧縮ポインタを検証して無限ループを防ぎ、ループバック以外の広告で送信先を変えない"
```

---

### Task 20: HiDPI・ウィンドウ配置・モーダルサイズ

**Files:**
- Create: `src/snoreguard/dpi.py`
- Modify: `src/main.py`（DPI 有効化を最初に、geometry 設定を削除）
- Modify: `src/snoreguard/ui.py:99-118`（`_setup_main_window`）
- Test: `tests/test_dpi.py`

**Interfaces:**
- Produces: `dpi.enable_dpi_awareness() -> bool`（Windows で成功したら True、それ以外 False。例外を出さない）

- [ ] **Step 1: テスト**

`tests/test_dpi.py`:

```python
import sys

from snoreguard import dpi


def test_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert dpi.enable_dpi_awareness() is False


def test_windows_path_uses_shcore(monkeypatch):
    import types

    calls = []
    shcore = types.SimpleNamespace(SetProcessDpiAwareness=lambda v: calls.append(v) or 0)
    windll = types.SimpleNamespace(shcore=shcore, user32=types.SimpleNamespace())
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dpi, "_windll", lambda: windll)
    assert dpi.enable_dpi_awareness() is True
    assert calls == [2]
```

- [ ] **Step 2: 実装**

`src/snoreguard/dpi.py`:

```python
"""Windows の DPI 認識。どの HWND よりも先に呼ぶ必要がある。"""

import logging
import sys

logger = logging.getLogger(__name__)


def _windll():
    import ctypes

    return ctypes.windll


def enable_dpi_awareness() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        windll = _windll()
        try:
            windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            windll.user32.SetProcessDPIAware()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"DPI 認識の設定に失敗: {e}")
        return False
```

`src/main.py`: `LOG_FILE = setup_logging()` の直後に `from snoreguard.dpi import enable_dpi_awareness` と `enable_dpi_awareness()` を追加（`QuickSplashScreen` の `tk.Tk()` より前）。`create_and_run_main_app` から `root.title(...)` と幅高さ計算・`root.geometry(...)` を削除（UIBuilder が担当）。

`ui.py` `_setup_main_window` を:

```python
    def _setup_main_window(self):
        """メインウィンドウの基本設定。画面に収まるサイズで中央に配置する。"""
        self.root.title(f"SnoreGuard Dashboard - v{__version__}")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1280, max(960, screen_w - 80))
        height = min(720, max(600, screen_h - 120))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(960, 600)
        self.root.configure(fg_color=self.COLOR_BG)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._set_window_icon()
```

- [ ] **Step 3: テスト・スモーク・コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import main; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/dpi.py src/main.py src/snoreguard/ui.py tests/test_dpi.py
git commit -m "fix: Tk ウィンドウ生成前に DPI 認識を有効化し、ウィンドウを画面内に収めて中央配置"
```

---

### Task 21: 停止時ミュート解除オプションとマニュアル更新

**Files:**
- Modify: `src/snoreguard/mute_policy.py`（`should_unmute_on_stop`）
- Modify: `src/snoreguard/app.py`（`_init_tk_variables`, `_update_ui_with_settings`, `_save_app_settings`, `_stop_detection`, `reset_settings`）
- Modify: `src/snoreguard/ui.py:401-417`（チェックボックス追加）
- Modify: `docs/MANUAL.md`, `README.md`
- Test: `tests/test_mute_policy.py`（追記）

**Interfaces:**
- Produces: `mute_policy.should_unmute_on_stop(enabled: bool, muted_by_snoreguard: bool, is_muted: bool | None) -> bool`、`SnoreGuardApp.unmute_on_stop_var: tk.BooleanVar`

- [ ] **Step 1: テスト追記**

`tests/test_mute_policy.py` に追加:

```python
from snoreguard.mute_policy import should_unmute_on_stop


def test_unmute_only_when_enabled_and_we_muted():
    assert should_unmute_on_stop(True, True, True) is True
    assert should_unmute_on_stop(False, True, True) is False
    assert should_unmute_on_stop(True, False, True) is False  # 利用者自身のミュートは触らない
    assert should_unmute_on_stop(True, True, False) is False
    assert should_unmute_on_stop(True, True, None) is False
```

- [ ] **Step 2: 実装**

`mute_policy.py` に追加:

```python
def should_unmute_on_stop(
    enabled: bool, muted_by_snoreguard: bool, is_muted: bool | None
) -> bool:
    """検出停止時にミュートを解除するか。SnoreGuard 自身がミュートした場合のみ。"""
    return bool(enabled and muted_by_snoreguard and is_muted is True)
```

`app.py`:
- `_init_tk_variables` に `self.unmute_on_stop_var = tk.BooleanVar()`。
- `_update_ui_with_settings` に `self.unmute_on_stop_var.set(settings.unmute_on_stop)`。
- `_save_app_settings` に `self.app_settings["unmute_on_stop"] = self.unmute_on_stop_var.get()`。
- `reset_settings` に `self.unmute_on_stop_var.set(defaults.unmute_on_stop)`。
- `_stop_detection` の `self.audio_service.stop()` の直後:

```python
        if should_unmute_on_stop(
            self.unmute_on_stop_var.get(), self.muted_by_snoreguard, self.is_vrchat_muted
        ):
            self.add_log("検出停止に伴い VRChat のミュートを解除します。", "osc")
            self.vrc_handler.toggle_mute()
            self.muted_by_snoreguard = False
```

（import に `should_unmute_on_stop` を追加。）

`ui.py` `_create_control_card` のチェックボックス群に追加（`checkbox_frame` の 2 行目として）:

```python
        ctk.CTkCheckBox(
            card,
            text="検出停止時にミュートを解除（SnoreGuard がミュートした場合のみ）",
            variable=app.unmute_on_stop_var,
            command=lambda: app._save_app_settings(),
            font=self.font_s,
        ).grid(row=6, column=0, padx=10, pady=(0, 10), sticky="w")
```

- [ ] **Step 3: 文書**

`docs/MANUAL.md` に節「VRChat 連携の前提と注意」を追加（既存の OSC 説明の直後）:

```markdown
### VRChat 連携の前提と注意

- **マイクモードは Toggle にしてください。** SnoreGuard は VRChat の `/input/Voice` を「押して離す」ことでミュートを切り替えます。Push-to-Talk 設定では機能しません。
- **ミュートは自動では解除されません。** 起床後に会話する前に VRChat 側でミュートを解除してください。「検出停止時にミュートを解除」を有効にすると、SnoreGuard 自身がミュートした場合に限り、検出停止（手動・スケジューラ終了）時に解除します。
- **受信ポート 9001 が他のアプリ（VRCFaceTracking 等）に使われていると、VRChat のミュート状態を追跡できません。** この場合、SnoreGuard は誤ってミュートを解除しないよう自動ミュートを送信しません。ダッシュボードの「VRChat:」表示が赤のときは該当アプリを終了して SnoreGuard を再起動してください。
- **接続表示の意味**: 「接続中」は VRChat からパラメータを受信した実績がある状態です。VRChat を起動してアバターが読み込まれると受信が始まります。
- **ログファイル**: `%LOCALAPPDATA%\SnoreGuard\logs\snoreguard.log` に動作ログが残ります。不具合報告の際に添付してください。
```

`README.md` の注意事項に「VRChat のマイクモードは Toggle が必要」「ミュートは自動解除されない（オプションあり）」の 2 点を追記。

- [ ] **Step 4: テスト・スモーク・コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.ui; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/mute_policy.py src/snoreguard/app.py src/snoreguard/ui.py tests/test_mute_policy.py
git commit -m "feat: 検出停止時にミュートを解除するオプションを追加（SnoreGuard 自身がミュートした場合のみ）"
git add docs/MANUAL.md README.md
git commit -m "docs: Toggle モード必須・ミュート非自動解除・9001 競合・ログ位置をマニュアルに明記"
```

---

### Task 22: Phase 2 の仕上げ

- [ ] **Step 1: 全テスト・lint・import スモーク**

Run: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import main, snoreguard.app, snoreguard.ui, snoreguard.calibration_modal; print('import ok')"`

- [ ] **Step 2: GUI スモーク（可能なら）**

Phase 1 Task 12 と同様。起動 → 「検出開始」→ 接続インジケータが「未確認（受信待ち）」→「検出停止」で 1 秒固まらない → リセットで確認ダイアログ → 終了でプロセスが残らない、を目視。

- [ ] **Step 3: コミット**

```bash
git add docs/superpowers/plans/2026-08-23-windows-refresh-phase2.md
git commit -m "docs: Phase 2 実装計画の進捗を更新"
```
