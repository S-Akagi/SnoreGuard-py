# SnoreGuard Windows 版改修 — Phase 1 実装計画（就寝中のミュートを確実にする）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 監査で P0 とされた「寝ている間にミュートが効かない／逆に外れる」欠陥と、その検証基盤（テスト・ログ・CI）を整える。

**Architecture:** 既存のモジュール構成（`src/core` = 検出ロジック、`src/snoreguard` = アプリ/UI/VRC）は維持し、(1) 設定オブジェクトは差し替えず `copy_from` で同期、(2) 音声ワーカーの終了はコールバックで App に伝播、(3) セグメント化をチャンク跨ぎの状態機械にする、(4) ミュート送信は状態既知のときだけ、という 4 つの不変条件を導入する。GUI 非依存のロジックはすべて `tests/` の pytest で検証する。

**Tech Stack:** Python 3.11 / uv / pytest / ruff / numpy・scipy・librosa / CustomTkinter / python-osc / PyInstaller

**Spec:** `docs/superpowers/specs/2026-08-23-windows-refresh-audit.md`

## 実行状況（2026-08-29 時点・Phase 1 完了）

**Task 1〜12 すべて完了。** ブランチ `feature/windows-refresh`。
全 66 テスト green、`ruff check` / `ruff format --check` クリーン、`uv lock --check` OK、
import スモーク・GUI 起動スモーク（macOS）ともに成功。

| Task | 状態 | コミット |
|---|---|---|
| 1. pyproject / CI / テスト基盤 | ✅ レビュー合格 | `ca7b656`, `0b92053` |
| 2. `winsound` の隔離（`snoreguard.notify`） | ✅ レビュー合格 | `8df5f6a` |
| 3. ファイルログと例外フック | ✅ 修正1回で合格 | `f52cd76`, `ca923a5` |
| 4. 設定ファイル読込の堅牢化 | ✅ レビュー合格 | `b0cd843` |
| 5. `RuleSettings` の検証・クランプ・コピー | ✅ 修正1回で合格 | `9c51360`, `e44b19e` |
| 6. 参照ズレの修正と相互制約の UI 適用 | ✅ 修正1回で合格 | `8c6492f`, `d52e511` |
| 7. 特徴量フォールバックの廃止 | ✅ レビュー合格 | `a15a389` |
| 8. ストリーム停止の伝播・自動再開・無音監視 | ✅ レビュー合格（2 件を Phase 2 Task 14 へ） | `c8d8aab`, `d3ec881` |
| 9. ミュート判断ポリシー・受信ポート・単一起動 | ✅ 修正1回で合格（1 件を Phase 2 Task 15 へ） | `99d01be`, `6a9ebe3`, `8b6a808`, `0870cc5` |
| 10. チャンク跨ぎセグメント・間隔検証・フィルタ状態 | ✅ レビュー合格 | `e2854a6`, `0d161b2`, `a838a13` |
| 11. pyin の広帯域化（＋スキップ時のセグメント破棄） | ✅ レビュー合格 | `46f85df`, `e421647` |
| 12. Phase 1 の仕上げ（検証・スモーク） | ✅ 完了 | — |

**GUI 起動スモークで確認できたこと（macOS, 2026-08-29）:** `winsound` スタブ無しで起動、
`~/.snoreguard/logs/snoreguard.log` にファイルログ出力、`VRCHandler開始完了 (受信: OK)`、
設定読み込み成功、ダッシュボード描画正常（v1.4.0-beta.3）。
なお「VRChat 接続中」の緑表示は送信クライアント生成だけで点灯する既知の問題で、Phase 2 Task 15 が実測表示に置き換える。

**次のステップ:** `docs/superpowers/plans/2026-08-23-windows-refresh-phase2.md` を Task 13 から実行する。

### Task 8 から Phase 2 への持ち越し（レビュー指摘・要対応）

Phase 2 の Task 14（スケジューラのレベル評価・非対話経路の再試行）で必ず解消すること。

1. **再試行ラダーが 1 回で止まる。** `_retry_start_detection` → `_start_detection` →
   `_initialize_audio_system` のデバイス事前テストが失敗すると `_handle_initialization_error` が
   modal `messagebox` を出して終わり、`RESTART_DELAYS_S` の 10/20/40/60 秒と諦め時のビープに到達しない。
   Task 14 の `origin` 引数（非対話経路ではダイアログを出さず再試行）で解消する。
2. **初期化中のストリーム死亡が握り潰される。** `audio_service.start()` 直後〜
   `_finalize_detection_start` までの窓でワーカーが死ぬと、`_handle_stream_stopped` は
   `app.is_running == False` のため早期 return し、UI は「検出中」のまま。
   `_finalize_detection_start` で `audio_service.is_running` / `last_error` を確認するガードを追加する。
3. （Minor）`_check_silence` の復帰時に `status_label_var` が「⚠ 無音が続いています」のまま戻らない。
   Task 15 の `_set_detection_status` 導入時に併せて直す。

## Global Constraints

- Python `>=3.11`。依存は uv 管理（`uv.lock` をコミット）。`uv run` は常に `--no-sync` か `uv sync --locked` 後に実行。
- 対象 OS は Windows 10/11。ただし **macOS/Linux でも `import snoreguard.app` とテストが通る**こと（`winsound` は `snoreguard.notify` に隔離）。
- コミットは小さく、`type: 日本語要約`（feat/fix/refactor/test/build/ci/docs/style）。**Author / Co-Authored-By / 本文に Claude・AI 生成の記載を入れない。** `git commit` は `-m` のみで行い trailer を付けない。
- 検出エンジン定数: `SAMPLE_RATE=16000, FRAME_LENGTH=800, HOP_LENGTH=200`, 帯域通過 80–1600Hz, 分析チャンク 1.0 秒（= 81 フレーム）。
- VRChat OSC: 送信 `127.0.0.1:9000`、受信 `127.0.0.1:9001`、ミュートは `/input/Voice` 1→0。
- 設定: `%APPDATA%\SnoreGuard\snore_guard_settings.json`。ログ: `%LOCALAPPDATA%\SnoreGuard\logs\snoreguard.log`。
- コメント・UI 文言・ログは日本語。各タスクの最後に `uv run --no-sync ruff check . && uv run --no-sync ruff format .` を通してからコミット。
- 実行コマンドはリポジトリルート（`/Users/akagi/Documents/GitHub/SnoreGuard-py`）で行う。テストは `uv run --no-sync pytest -q`。
- GUI（Tk）を必要とするコードは自動テスト対象外。変更した GUI コードは `uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.ui, snoreguard.calibration_modal"` で import スモークを必ず行う。

---

## ファイル構成（Phase 1 で触るもの）

| ファイル | 責務 | 変更 |
|---|---|---|
| `pyproject.toml` | 依存・ツール設定 | 3.11 統一、packaging 追加、pyinstaller を build グループへ、pytest 設定 |
| `.github/workflows/CI.yml` | CI | uv 化、lock 検証、pytest、Windows スモーク＋ビルド |
| `scripts/build.bat`, `SnoreGuard.spec`, `README.md` | ビルド | ルートへ cd、`--locked`、`upx=False`、手順一本化 |
| `src/snoreguard/notify.py` | **新規** ビープ音（winsound 隔離） | |
| `src/snoreguard/logging_setup.py` | **新規** ファイルログ・例外フック | |
| `src/main.py` | 起動 | ログ初期化、致命エラー表示、単一起動、DPI |
| `src/snoreguard/settings_manager.py` | 設定 I/O | 壊れたファイルの退避・通知 |
| `src/core/settings.py` | 設定データクラス | `SLIDER_RANGES`, `FIELD_LABELS`, `copy_from/from_dict/sanitized/validate/diff` |
| `src/core/rule_processor.py` | 検出エンジン | フォールバック廃止、チャンク跨ぎセグメント、サンプルクロック、間隔検証、`sosfilt_zi` |
| `src/snoreguard/audio_service.py` | 音声ワーカー | `on_stream_stopped` コールバック |
| `src/snoreguard/mute_policy.py` | **新規** ミュート判断（純粋関数） | |
| `src/snoreguard/vrc/handler.py` | OSC 受信 | bind 失敗の伝播 |
| `src/snoreguard/app.py` | アプリ | 上記の配線、参照ズレ修正、無音ウォッチドッグ |
| `src/snoreguard/ui.py` | UI | `SLIDER_RANGES` 参照 |
| `tests/` | **新規** pytest | |

---

### Task 1: プロジェクト整合とテスト基盤（pyproject / CI / ビルド手順）

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/CI.yml`
- Modify: `scripts/build.bat`, `SnoreGuard.spec:45`, `README.md`（「インストール方法（開発者向け）」節）
- Delete: `requirements.txt`
- Create: `tests/__init__.py`（空）, `tests/test_smoke.py`

**Interfaces:**
- Produces: `[tool.pytest.ini_options] pythonpath=["src"]`（以降のテストはすべて `from core... / from snoreguard...` で import できる）、dependency group `dev`（ruff, pytest）と `build`（pyinstaller）。

- [x] **Step 1: pyproject.toml を書き換える**

`[project]` と `[dependency-groups]`、ruff、pytest の部分を以下にする（`[tool.ruff]` の `exclude`/`format` ブロックは既存のまま残す）:

```toml
[project]
name = "snoreguard-py"
version = "1.4.0-beta.3"
description = "snoreguard by python"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "customtkinter>=5.2.2",
    "librosa>=0.9.2",
    "matplotlib>=3.5.0",
    "numpy>=1.24.0",
    "packaging>=23.0",
    "python-osc>=1.9.3",
    "requests>=2.33.0",
    "scipy>=1.10.0",
    "sounddevice>=0.4.6",
]

[dependency-groups]
dev = [
    "ruff>=0.11.13",
    "pytest>=8.3",
]
build = [
    "pyinstaller>=6.14.1",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
filterwarnings = ["ignore::UserWarning:librosa"]
```

`[tool.ruff]` の `target-version = "py310"` を `target-version = "py311"` に変更する。`[tool.ruff.lint]` は変更しない。

- [x] **Step 2: lock を更新して同期する**

Run: `uv lock && uv sync --locked --all-groups`
Expected: `Resolved ... packages`、エラーなし。`uv run --no-sync python -c "import pytest, PyInstaller, packaging; print('ok')"` が `ok`。

- [x] **Step 3: スモークテストを書く**

`tests/__init__.py` は空ファイル。`tests/test_smoke.py`:

```python
"""GUI 非依存モジュールが import できることを確認する。"""


def test_core_imports():
    import core.rule_processor  # noqa: F401
    import core.settings  # noqa: F401


def test_service_imports():
    import snoreguard.settings_manager  # noqa: F401
    import snoreguard.time_scheduler  # noqa: F401
    import snoreguard.updater  # noqa: F401
    import snoreguard.vrc.mdns_client  # noqa: F401
```

- [x] **Step 4: テストを実行して通ることを確認**

Run: `uv run --no-sync pytest -q`
Expected: `2 passed`

- [x] **Step 5: requirements.txt を削除し、ビルド手順を一本化する**

`git rm requirements.txt`。

`scripts/build.bat` を以下に置き換える:

```bat
@echo off
chcp 65001 >nul
rem リポジトリルートへ移動（どこから実行しても同じ結果にする）
cd /d "%~dp0.."

echo [1/3] 依存関係を lock どおりに同期します...
uv sync --locked --no-dev --group build
if errorlevel 1 exit /b 1

echo [2/3] PyInstaller でビルドします...
uv run --no-sync pyinstaller SnoreGuard.spec --clean
if errorlevel 1 exit /b 1

echo [3/3] 完了: dist\SnoreGuard.exe
```

`SnoreGuard.spec` の `upx=True,` を `upx=False,` に変更する（UPX 圧縮は AV 誤検知と環境依存の原因になるため）。

`README.md` の開発者向けセットアップ節（「python src/main.py」「pyinstaller --noconfirm ...」「requirements.txt」「Python 3.10」を含む箇所）を以下に置き換える:

```markdown
## 開発者向け: ソースから実行・ビルドする

Python 3.11 以上と [uv](https://docs.astral.sh/uv/) が必要です。

```bash
uv sync --locked --all-groups   # 依存関係を lock どおりに導入
uv run --no-sync python src/main.py   # 実行
uv run --no-sync pytest -q      # テスト
```

Windows 用の実行ファイルは `scripts\build.bat` で作成します（`dist\SnoreGuard.exe`）。
```

- [x] **Step 6: CI を uv 化し Windows ジョブを追加する**

`.github/workflows/CI.yml` を以下に置き換える:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv python install
      - run: uv lock --check
      - run: uv sync --locked --all-groups
      - run: uv run --no-sync ruff check .
      - run: uv run --no-sync ruff format --check .
      - run: uv run --no-sync pytest -q

  windows-smoke:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv python install
      - run: uv sync --locked --all-groups
      - run: uv run --no-sync pytest -q
      - run: uv run --no-sync python -c "import sys; sys.path.insert(0, 'src'); import snoreguard.app, snoreguard.ui, snoreguard.calibration_modal; print('import ok')"
      - run: uv run --no-sync pyinstaller SnoreGuard.spec --clean
      - uses: actions/upload-artifact@v4
        with:
          name: SnoreGuard-win64
          path: dist/
```

- [x] **Step 7: lint / format を通す**

Run: `uv run --no-sync ruff check . && uv run --no-sync ruff format .`
Expected: `All checks passed!`

- [x] **Step 8: コミット（2 つに分ける）**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/test_smoke.py
git commit -m "build: Python 3.11 に統一し pytest 基盤と build グループを追加"
git add .github/workflows/CI.yml scripts/build.bat SnoreGuard.spec README.md
git rm -q requirements.txt
git commit -m "ci: uv ベースの lint/test と Windows ビルドスモークに置き換え、ビルド手順を build.bat に一本化"
```

---

### Task 2: `winsound` の隔離（`snoreguard.notify`）

**Files:**
- Create: `src/snoreguard/notify.py`
- Modify: `src/snoreguard/app.py:7`（`import winsound` 削除）, `src/snoreguard/app.py:503-517`（`_handle_detection_event`）
- Test: `tests/test_notify.py`

**Interfaces:**
- Produces: `snoreguard.notify.beep(frequency: int = 1000, duration_ms: int = 200) -> None`（非同期、Windows 以外は no-op、例外を外に出さない）

- [x] **Step 1: 失敗するテストを書く**

`tests/test_notify.py`:

```python
import sys
import types

from snoreguard import notify


def test_beep_is_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    notify.beep()  # 例外が出ないこと


def test_beep_calls_winsound_in_background_on_windows(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(Beep=lambda f, d: calls.append((f, d)))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    thread = notify.beep(880, 50)
    assert thread is not None
    thread.join(timeout=2)
    assert calls == [(880, 50)]


def test_beep_swallows_winsound_errors(monkeypatch):
    def boom(f, d):
        raise RuntimeError("no sound device")

    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(Beep=boom))
    monkeypatch.setattr(sys, "platform", "win32")
    thread = notify.beep()
    thread.join(timeout=2)  # 例外はスレッド内で握られ、ここには伝播しない
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_notify.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'snoreguard.notify'`）

- [x] **Step 3: 実装**

`src/snoreguard/notify.py`:

```python
"""PC 通知音。Windows 専用の winsound をここに隔離する。"""

import logging
import sys
import threading

logger = logging.getLogger(__name__)


def beep(frequency: int = 1000, duration_ms: int = 200) -> threading.Thread | None:
    """ビープ音を別スレッドで鳴らす。

    - Windows 以外では何もしない（None を返す）
    - 再生失敗は警告ログにとどめ、呼び出し元には伝播させない
    - 戻り値のスレッドはテスト用（join できる）
    """
    if not sys.platform.startswith("win"):
        return None

    def _run() -> None:
        try:
            import winsound

            winsound.Beep(frequency, duration_ms)
        except Exception as e:  # noqa: BLE001 - 通知音の失敗で本処理を止めない
            logger.warning(f"ビープ音の再生に失敗: {e}")

    thread = threading.Thread(target=_run, daemon=True, name="notify-beep")
    thread.start()
    return thread
```

`src/snoreguard/app.py`: 7 行目の `import winsound` を削除し、import 群に `from snoreguard import notify` を追加。`_handle_detection_event` を以下に置き換える（**ミュート送信をビープより先に**する）:

```python
    def _handle_detection_event(self):
        """いびき検出イベント処理"""
        if not self.is_running:
            logger.debug("検出イベントをスキップ: システム停止中")
            return
        logger.info("いびき検出イベント発生")
        self.add_log("いびきを検出しました！", "detection")
        self.status_label_var.set("イビキ検出!")
        if self.auto_mute_var.get():
            self._trigger_vrchat_mute()
        if self.notification_var.get():
            notify.beep(1000, 200)
        self.root.after(
            2000, lambda: self.is_running and self.status_label_var.set("🔊 検出中...")
        )
```

- [x] **Step 4: テストと import スモーク**

Run: `uv run --no-sync pytest tests/test_notify.py -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app; print('import ok')"`
Expected: `3 passed` と `import ok`（macOS でも app.py が import できるようになる）

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/notify.py src/snoreguard/app.py tests/test_notify.py
git commit -m "refactor: winsound を notify モジュールに隔離し、ミュート送信をビープより先に実行"
```

---

### Task 3: ファイルログと例外フック（windowed exe で消える問題）

**Files:**
- Create: `src/snoreguard/logging_setup.py`
- Modify: `src/main.py`（全体）
- Modify: `src/snoreguard/quick_splash.py:196-207`（init_thread の except）
- Test: `tests/test_logging_setup.py`

**Interfaces:**
- Produces:
  - `logging_setup.get_log_dir() -> Path`
  - `logging_setup.setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path`（戻り値はログファイルパス）
  - `logging_setup.install_excepthooks() -> None`
  - `logging_setup.install_tk_report_callback(root) -> None`
  - `logging_setup.show_fatal_error(message: str) -> None`（Tk の messagebox を出す。失敗しても例外を出さない）

- [x] **Step 1: 失敗するテストを書く**

`tests/test_logging_setup.py`:

```python
import logging
import sys

from snoreguard import logging_setup


def test_setup_logging_writes_to_file(tmp_path):
    log_file = logging_setup.setup_logging(log_dir=tmp_path)
    logging.getLogger("test.x").info("こんにちは")
    for h in logging.getLogger().handlers:
        h.flush()
    assert log_file == tmp_path / "snoreguard.log"
    assert "こんにちは" in log_file.read_text(encoding="utf-8")


def test_setup_logging_without_stderr_adds_only_file_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    logging_setup.setup_logging(log_dir=tmp_path)
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.FileHandler)


def test_get_log_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logging_setup.get_log_dir() == tmp_path / "SnoreGuard" / "logs"


def test_install_excepthooks_logs_thread_exception(tmp_path):
    import threading

    log_file = logging_setup.setup_logging(log_dir=tmp_path)
    logging_setup.install_excepthooks()

    def boom():
        raise ValueError("thread failure")

    t = threading.Thread(target=boom)
    t.start()
    t.join()
    for h in logging.getLogger().handlers:
        h.flush()
    assert "thread failure" in log_file.read_text(encoding="utf-8")
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_logging_setup.py -q`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 実装**

`src/snoreguard/logging_setup.py`:

```python
"""ログ出力と未捕捉例外の記録。

windowed exe（console=False）では sys.stderr が None になり、標準の
logging.basicConfig では全ログが消える。ここでは常にファイルへ書き、
stderr があるときだけ併せて出力する。
"""

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_log_dir() -> Path:
    """ログディレクトリ。Windows は %LOCALAPPDATA%\\SnoreGuard\\logs。"""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "SnoreGuard" / "logs"
    return Path.home() / ".snoreguard" / "logs"


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    """ルートロガーを構成し、ログファイルのパスを返す。"""
    log_dir = log_dir or get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "snoreguard.log"

    formatter = logging.Formatter(LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    logging.getLogger(__name__).info(f"ログ出力先: {log_file}")
    return log_file


def install_excepthooks() -> None:
    """メインスレッド・サブスレッドの未捕捉例外をログに残す。"""
    log = logging.getLogger("snoreguard.unhandled")

    def _sys_hook(exc_type, exc_value, exc_tb):
        log.critical("未捕捉例外", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args: threading.ExceptHookArgs):
        name = args.thread.name if args.thread else "?"
        log.critical(
            f"スレッド {name} で未捕捉例外",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def install_tk_report_callback(root) -> None:
    """Tk コールバック内の例外（通常は stderr に出るだけ）をログへ。"""
    log = logging.getLogger("snoreguard.tk")

    def _report(exc_type, exc_value, exc_tb):
        log.error("Tk コールバック内で例外", exc_info=(exc_type, exc_value, exc_tb))

    root.report_callback_exception = _report


def show_fatal_error(message: str) -> None:
    """起動失敗などをダイアログで知らせる。Tk が使えない場合は黙って戻る。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        hidden = tk.Tk()
        hidden.withdraw()
        messagebox.showerror("SnoreGuard - 起動エラー", message)
        hidden.destroy()
    except Exception:  # noqa: BLE001 - ここで失敗しても打つ手がない
        pass
```

`src/main.py` を以下に置き換える（ログ初期化を**どの import よりも先**に、かつ Tk ウィンドウ生成前に行う）:

```python
#!/usr/bin/env python3
"""SnoreGuard エントリポイント。"""

import logging
import sys
import time
import traceback

from snoreguard.logging_setup import (
    install_excepthooks,
    install_tk_report_callback,
    setup_logging,
    show_fatal_error,
)

LOG_FILE = setup_logging()
install_excepthooks()
logger = logging.getLogger(__name__)

import customtkinter as ctk  # noqa: E402 - ログ初期化後に import する

from snoreguard.app import SnoreGuardApp  # noqa: E402
from snoreguard.quick_splash import QuickSplashScreen  # noqa: E402


def prepare_app_data(status_callback):
    """
    アプリケーションの初期化処理を実行
    - 音声分析エンジンのプリコンパイル（librosa/numba の初回 JIT）
    - スプラッシュ画面に進捗を表示
    """
    status_callback("システム初期化中...")
    status_callback("音声エンジン準備中...")
    from core.rule_processor import RuleBasedProcessor
    from core.settings import RuleSettings

    RuleBasedProcessor(RuleSettings(), lambda: None)
    status_callback("設定読み込み中...")
    return True


def create_and_run_main_app():
    """メインアプリケーションウィンドウを作成して実行"""
    root = ctk.CTk()
    install_tk_report_callback(root)
    root.title("SnoreGuard - いびき検出アプリ")
    SnoreGuardApp(root)
    root.deiconify()
    root.lift()
    root.focus_force()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))
    root.update()
    root.mainloop()


def main():
    """
    - スプラッシュ画面の表示とバックグラウンド初期化
    - 初期化完了後にメインアプリケーションウィンドウを表示
    - 失敗時はログに残し、ダイアログで利用者に知らせる
    """
    splash = QuickSplashScreen()
    initialization_complete = False

    def end_splash_and_show_main():
        if initialization_complete:
            splash.splash_root.quit()

    def on_initialization_complete():
        nonlocal initialization_complete
        initialization_complete = True
        splash.splash_root.after(300, end_splash_and_show_main)

    splash.on_initialization_complete = on_initialization_complete
    splash.start_initialization(prepare_app_data)
    splash.run()

    if not initialization_complete:
        message = (
            "初期化に失敗しました。音声エンジンの準備中にエラーが発生しています。\n"
            f"ログ: {LOG_FILE}"
        )
        logger.error(message)
        show_fatal_error(message)
        return 1

    splash.close()
    time.sleep(0.1)
    create_and_run_main_app()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        logger.critical("起動中に致命的なエラー", exc_info=True)
        show_fatal_error(
            "SnoreGuard の起動に失敗しました。\n\n"
            f"{traceback.format_exc(limit=3)}\n"
            f"詳細はログを確認してください: {LOG_FILE}"
        )
        raise
```

`src/snoreguard/quick_splash.py` の `init_thread` の except 節（`print(f"初期化エラー: {e}")` の箇所）を次に置き換える:

```python
            except Exception as e:
                logger.error(f"初期化エラー: {e}", exc_info=True)
                self.update_status("エラーが発生しました")
                time.sleep(2)  # エラーメッセージを見せるための待機
                if self.splash_root:
                    self.splash_root.after(0, self.close)
```

ファイル先頭に `import logging` と `logger = logging.getLogger(__name__)` を追加する。

- [x] **Step 4: テストと import スモーク**

Run: `uv run --no-sync pytest tests/test_logging_setup.py -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import main; print('import ok')"`
Expected: `4 passed`、`import ok`（`~/.snoreguard/logs/snoreguard.log` が作られる）

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/logging_setup.py src/main.py src/snoreguard/quick_splash.py tests/test_logging_setup.py
git commit -m "feat: ローテーション付きファイルログと未捕捉例外フックを追加し、起動失敗をダイアログで通知"
```

---

### Task 4: 設定ファイル読込の堅牢化（壊れた JSON で無言終了しない）

**Files:**
- Modify: `src/snoreguard/settings_manager.py:28-62`
- Modify: `src/snoreguard/app.py`（`__init__` の直後に通知を追加）
- Test: `tests/test_settings_manager.py`

**Interfaces:**
- Produces: `SettingsManager.last_error: str | None`（直近の load で壊れたファイルを退避した場合のメッセージ）、`SettingsManager.backup_path: Path | None`

- [x] **Step 1: 失敗するテストを書く**

`tests/test_settings_manager.py`:

```python
import json

from snoreguard.settings_manager import SettingsManager

DEFAULTS = {"a": 1, "nested": {"b": 2}}


def test_roundtrip(tmp_path):
    sm = SettingsManager(tmp_path / "s.json")
    sm.save({"a": 5, "nested": {"b": 9}})
    loaded = SettingsManager(tmp_path / "s.json").load(DEFAULTS)
    assert loaded == {"a": 5, "nested": {"b": 9}}
    assert not (tmp_path / "s.tmp").exists()


def test_missing_file_returns_defaults_copy(tmp_path):
    sm = SettingsManager(tmp_path / "s.json")
    loaded = sm.load(DEFAULTS)
    assert loaded == DEFAULTS
    assert loaded is not DEFAULTS
    assert sm.last_error is None


def test_non_utf8_file_is_backed_up_and_defaults_used(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes('{"mic_device_name": "マイク"}'.encode("shift_jis"))
    sm = SettingsManager(path)
    loaded = sm.load(DEFAULTS)
    assert loaded == DEFAULTS
    assert sm.last_error is not None
    assert sm.backup_path is not None and sm.backup_path.exists()
    assert not path.exists()


def test_non_dict_json_is_backed_up(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    sm = SettingsManager(path)
    assert sm.load(DEFAULTS) == DEFAULTS
    assert sm.last_error is not None


def test_invalid_json_is_backed_up(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    sm = SettingsManager(path)
    assert sm.load(DEFAULTS) == DEFAULTS
    assert sm.backup_path.name.endswith(".bak")
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_settings_manager.py -q`
Expected: 3 件 FAIL（`last_error` 属性なし、UnicodeDecodeError が伝播）

- [x] **Step 3: 実装**

`settings_manager.py` の `__init__` に次を追加:

```python
        self.last_error: str | None = None  # 直近の読込で退避したときのメッセージ
        self.backup_path: Path | None = None  # 退避先
```

`load()` を以下に置き換える:

```python
    def load(self, default_settings: dict[str, Any]) -> dict[str, Any]:
        """設定を読み込む。壊れていれば .bak に退避して既定値を返す。"""
        logger.debug(f"設定読み込み開始: {self.filepath}")
        self.last_error = None
        self.backup_path = None
        with self._cache_lock:
            if self.filepath.exists():
                current_mtime = self.filepath.stat().st_mtime
                if (
                    self._cache is not None
                    and self._file_mtime is not None
                    and current_mtime == self._file_mtime
                ):
                    logger.debug("キャッシュから設定を返却")
                    return self._cache.copy()

                try:
                    with open(self.filepath, encoding="utf-8") as f:
                        settings = json.load(f)
                    if not isinstance(settings, dict):
                        raise ValueError(
                            f"設定ファイルの形式が不正です（{type(settings).__name__}）"
                        )
                    self._cache = settings
                    self._file_mtime = current_mtime
                    logger.info(f"設定ファイル読み込み完了: {len(settings)}個の設定")
                    return settings.copy()
                except (OSError, ValueError) as e:
                    # UnicodeDecodeError / JSONDecodeError はいずれも ValueError の派生
                    self._backup_corrupted_file(e)

            logger.debug("デフォルト設定を使用")
            self._cache = default_settings.copy()
            self._file_mtime = None
            return default_settings.copy()

    def _backup_corrupted_file(self, error: Exception) -> None:
        """壊れた設定ファイルを .bak に退避し、last_error に記録する。"""
        backup = self.filepath.with_name(self.filepath.name + ".bak")
        try:
            self.filepath.replace(backup)
            self.backup_path = backup
            self.last_error = (
                f"設定ファイルが壊れていたため初期化しました（退避先: {backup.name}）: {error}"
            )
        except OSError as move_error:
            self.last_error = f"設定ファイルを読み込めません（退避も失敗）: {error} / {move_error}"
        logger.error(self.last_error)
```

`settings_manager.py` の `print(...)` 2 箇所は削除する（windowed exe では無意味）。

`src/snoreguard/app.py` の `__init__` 内、`self.app_settings = self.settings_manager.load(...)` の直後ではなく、`self.root.after(100, self._update_ui_with_settings)` の直後に追加:

```python
        if self.settings_manager.last_error:
            self.root.after(1500, self._notify_settings_recovery)
```

`SnoreGuardApp` にメソッドを追加:

```python
    def _notify_settings_recovery(self):
        """壊れた設定ファイルを初期化したことを利用者に知らせる"""
        message = self.settings_manager.last_error or ""
        self.add_log(message, "warning")
        messagebox.showwarning("設定ファイルを初期化しました", message)
```

- [x] **Step 4: テスト**

Run: `uv run --no-sync pytest tests/test_settings_manager.py -q`
Expected: `5 passed`

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/settings_manager.py src/snoreguard/app.py tests/test_settings_manager.py
git commit -m "fix: 壊れた設定ファイルを .bak に退避して既定値で起動し、利用者に通知"
```

---

### Task 5: `RuleSettings` の検証・クランプ・コピー（参照ズレと逆転スライダーの土台）

**Files:**
- Modify: `src/core/settings.py`（全体）
- Modify: `src/snoreguard/ui.py:499-512`（`params` を `SLIDER_RANGES` 参照に）
- Test: `tests/test_rule_settings.py`

**Interfaces:**
- Produces（`core.settings`）:
  - `SLIDER_RANGES: dict[str, tuple[float, float, float]]`（name → (min, max, step)、UI とクランプの単一ソース）
  - `FIELD_LABELS: dict[str, str]`（name → 日本語ラベル）
  - `RuleSettings.copy_from(other: "RuleSettings") -> None`
  - `RuleSettings.from_dict(d: dict) -> "RuleSettings"`（型変換・不正値は既定値・最後に sanitized）
  - `RuleSettings.sanitized() -> "RuleSettings"`（範囲クランプと相互制約を満たした新しいインスタンス）
  - `RuleSettings.validate() -> list[str]`（問題点の説明、空なら OK）
  - `RuleSettings.diff(other) -> list[tuple[str, str, Any, Any]]`（(name, label, old, new) 変更のみ）

- [x] **Step 1: 失敗するテストを書く**

`tests/test_rule_settings.py`:

```python
from core.settings import FIELD_LABELS, SLIDER_RANGES, RuleSettings


def test_slider_ranges_cover_all_fields():
    from dataclasses import fields

    names = {f.name for f in fields(RuleSettings)}
    assert set(SLIDER_RANGES) == names
    assert set(FIELD_LABELS) == names


def test_copy_from_keeps_identity():
    a = RuleSettings()
    b = RuleSettings(energy_threshold=0.05, periodicity_event_count=7)
    a.copy_from(b)
    assert a.energy_threshold == 0.05
    assert a.periodicity_event_count == 7
    assert a is not b


def test_from_dict_coerces_and_falls_back():
    s = RuleSettings.from_dict(
        {"energy_threshold": "0.02", "periodicity_event_count": "abc", "unknown": 1}
    )
    assert s.energy_threshold == 0.02
    assert s.periodicity_event_count == RuleSettings().periodicity_event_count
    assert isinstance(s.periodicity_event_count, int)


def test_sanitized_clamps_to_slider_range():
    s = RuleSettings(energy_threshold=5.0, spectral_centroid_threshold=-10).sanitized()
    assert s.energy_threshold == SLIDER_RANGES["energy_threshold"][1]
    assert s.spectral_centroid_threshold == SLIDER_RANGES["spectral_centroid_threshold"][0]


def test_sanitized_enforces_f0_order():
    s = RuleSettings(f0_min_hz=150, f0_max_hz=100).sanitized()
    assert s.f0_min_hz < s.f0_max_hz
    s2 = RuleSettings(f0_min_hz=150, f0_max_hz=150).sanitized()
    assert s2.f0_min_hz < s2.f0_max_hz


def test_sanitized_enforces_duration_and_interval_order():
    s = RuleSettings(min_duration_seconds=1.0, max_duration_seconds=0.5).sanitized()
    assert s.min_duration_seconds <= s.max_duration_seconds
    s2 = RuleSettings(min_event_interval_seconds=9.0, max_event_interval_seconds=5.0).sanitized()
    assert s2.min_event_interval_seconds <= s2.max_event_interval_seconds


def test_validate_reports_problems():
    assert RuleSettings().validate() == []
    problems = RuleSettings(f0_min_hz=200, f0_max_hz=100, periodicity_event_count=0).validate()
    assert any("f0" in p for p in problems)
    assert any("periodicity_event_count" in p for p in problems)


def test_diff_lists_changed_fields_only():
    old = RuleSettings()
    new = RuleSettings(zcr_threshold=0.1)
    d = old.diff(new)
    assert d == [("zcr_threshold", FIELD_LABELS["zcr_threshold"], 0.06, 0.1)]
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_rule_settings.py -q`
Expected: ImportError（`SLIDER_RANGES` なし）

- [x] **Step 3: 実装**

`src/core/settings.py` を以下に置き換える:

```python
#!/usr/bin/env python3
"""検出ルール・スケジューラの設定データクラスと、その検証ユーティリティ。"""

import logging
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
    "f0_min_hz": (70, 150, 1),
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
            try:
                value = int(raw) if f.type is int else float(raw)
            except (TypeError, ValueError):
                logger.warning(f"設定 {f.name} の値 {raw!r} が不正なため既定値を使用")
                continue
            setattr(settings, f.name, value)
        return settings.sanitized()

    def sanitized(self) -> "RuleSettings":
        """スライダー範囲にクランプし、相互制約を満たした新しいインスタンスを返す"""
        s = RuleSettings()
        s.copy_from(self)
        for name, (lo, hi, _step) in SLIDER_RANGES.items():
            value = getattr(s, name)
            clamped = min(max(value, lo), hi)
            setattr(s, name, int(clamped) if isinstance(value, int) else float(clamped))

        if s.f0_min_hz + F0_MIN_GAP_HZ > s.f0_max_hz:
            s.f0_max_hz = min(s.f0_min_hz + F0_MIN_GAP_HZ, SLIDER_RANGES["f0_max_hz"][1])
            if s.f0_min_hz + F0_MIN_GAP_HZ > s.f0_max_hz:
                s.f0_min_hz = max(s.f0_max_hz - F0_MIN_GAP_HZ, SLIDER_RANGES["f0_min_hz"][0])
        if s.min_duration_seconds > s.max_duration_seconds:
            s.max_duration_seconds = s.min_duration_seconds
        if s.min_event_interval_seconds > s.max_event_interval_seconds:
            s.max_event_interval_seconds = s.min_event_interval_seconds
        s.periodicity_event_count = max(1, s.periodicity_event_count)
        return s

    def validate(self) -> list[str]:
        """問題点の一覧を返す（空なら OK）"""
        problems: list[str] = []
        for name, (lo, hi, _step) in SLIDER_RANGES.items():
            value = getattr(self, name)
            if not (lo <= value <= hi):
                problems.append(f"{name}={value} が範囲 [{lo}, {hi}] 外")
        if self.f0_min_hz >= self.f0_max_hz:
            problems.append(f"f0_min_hz({self.f0_min_hz}) >= f0_max_hz({self.f0_max_hz})")
        if self.min_duration_seconds > self.max_duration_seconds:
            problems.append("min_duration_seconds > max_duration_seconds")
        if self.min_event_interval_seconds > self.max_event_interval_seconds:
            problems.append("min_event_interval_seconds > max_event_interval_seconds")
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
```

`src/snoreguard/ui.py`: 先頭の import に `from core.settings import FIELD_LABELS, SLIDER_RANGES` を追加し、`_create_settings_card` 内の `params = [...]`（12 行のリスト）を次に置き換える:

```python
        params = [
            (name, FIELD_LABELS[name], SLIDER_RANGES[name]) for name in SLIDER_RANGES
        ]
```

- [x] **Step 4: テスト**

Run: `uv run --no-sync pytest tests/test_rule_settings.py -q`
Expected: `8 passed`

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/core/settings.py src/snoreguard/ui.py tests/test_rule_settings.py
git commit -m "feat: RuleSettings に copy_from/from_dict/sanitized/validate/diff を追加し、スライダー範囲を単一ソース化"
```

---

### Task 6: 参照ズレの修正と相互制約の UI 適用

**Files:**
- Modify: `src/snoreguard/app.py`（`_on_rule_setting_change`, `_update_rule_settings_ui`, `_update_ui_with_settings`, `reset_settings`, `_on_calibration_completed`, `_log_calibration_changes`, `_apply_settings_to_ui`）
- Modify: `src/snoreguard/calibration_modal.py:473-541`（`_display_calibration_changes`）
- Test: `tests/test_settings_sharing.py`

**Interfaces:**
- Consumes: Task 5 の `copy_from / from_dict / sanitized / diff / format_setting_value`
- Produces: `SnoreGuardApp.apply_rule_settings(new: RuleSettings, source: str) -> None`（唯一の「ルール設定を置き換える」入口。UI・共有オブジェクト・保存を一括で行う）

- [x] **Step 1: 失敗するテストを書く（検出器が共有オブジェクトの更新を見ること）**

`tests/test_settings_sharing.py`:

```python
import numpy as np

from core.rule_processor import MaskProcessor
from core.settings import RuleSettings


def test_mask_processor_sees_copy_from_updates():
    shared = RuleSettings(energy_threshold=0.5)
    mp = MaskProcessor(max_frames=10, settings=shared)
    feats = {
        "rms": np.full(10, 0.1, dtype=np.float32),
        "voiced_probs": np.ones(10, dtype=np.float32),
        "f0": np.full(10, 100.0, dtype=np.float32),
        "spectral_centroid": np.full(10, 400.0, dtype=np.float32),
        "zcr": np.full(10, 0.01, dtype=np.float32),
    }
    _, final_before = mp.create_masks(feats)
    assert not final_before.any()  # 0.1 < 0.5 なのでエネルギーで落ちる

    shared.copy_from(RuleSettings(energy_threshold=0.05))  # 差し替えではなくコピー
    _, final_after = mp.create_masks(feats)
    assert final_after.all()
```

- [x] **Step 2: 失敗しないことを確認（これは回帰防止テスト。現状でも通る）**

Run: `uv run --no-sync pytest tests/test_settings_sharing.py -q`
Expected: `1 passed`（通ることを確認してから app.py を直す）

- [x] **Step 3: app.py の配線を直す**

`app.py` の import に `from core.settings import RuleSettings, TimeSchedulerSettings, format_setting_value` を追加（既存の `from core.settings import RuleSettings, TimeSchedulerSettings` を置き換え）。

`_on_rule_setting_change` を以下に置き換える（ペアのスライダーを相互にクランプ）:

```python
    def _on_rule_setting_change(
        self, name: str, value_str: str, label_var: tk.StringVar, is_int: bool
    ):
        """スライダー操作。共有オブジェクトを直接更新し、相互制約を保つ"""
        value = round(float(value_str)) if is_int else float(value_str)
        setattr(self.rule_settings, name, value)
        sanitized = self.rule_settings.sanitized()
        if sanitized != self.rule_settings:
            # 相手側スライダー（f0_max など）を押し上げた場合は UI にも反映
            self.rule_settings.copy_from(sanitized)
            self._update_rule_settings_ui()
        else:
            label_var.set(format_setting_value(value))
```

`_update_rule_settings_ui` を以下に置き換える:

```python
    def _update_rule_settings_ui(self):
        """共有オブジェクトの値をスライダーとラベルへ反映"""
        for name, (var, label_var, _) in self.rule_setting_vars.items():
            value = getattr(self.rule_settings, name)
            var.set(value)
            label_var.set(format_setting_value(value))
```

`_update_ui_with_settings` の `if rule_settings_dict := ...` ブロック（setattr ループ）を以下に置き換える:

```python
        if rule_settings_dict := self.app_settings.get("rule_settings"):
            self.rule_settings.copy_from(RuleSettings.from_dict(rule_settings_dict))
```

新しいメソッドを追加（`reset_settings` の直前）:

```python
    def apply_rule_settings(self, new_settings: RuleSettings, source: str):
        """ルール設定を置き換える唯一の入口。

        検出エンジンは self.rule_settings への参照を保持しているため、
        新しいオブジェクトを代入せず copy_from で中身だけ更新する。
        """
        sanitized = new_settings.sanitized()
        changes = self.rule_settings.diff(sanitized)
        self.rule_settings.copy_from(sanitized)
        self._update_rule_settings_ui()
        self.audio_service.reset_processor_periodicity()
        self._save_app_settings(send_feedback=False)
        if changes:
            self.add_log(f"=== {source}による設定変更 ===", "info")
            for _name, label, old, new in changes:
                self.add_log(
                    f"  {label}: {format_setting_value(old)} → {format_setting_value(new)}",
                    "info",
                )
        else:
            self.add_log(f"{source}: 変更された設定項目はありません", "info")
```

`reset_settings` を以下に置き換える（スケジューラ停止とチェックボックス復帰は Phase 2 Task 11 で完成させるが、ここで `rule_settings` の差し替えをやめる）:

```python
    def reset_settings(self):
        """設定をデフォルト値にリセット"""
        if not messagebox.askyesno(
            "設定のリセット", "ルール設定をすべて初期値に戻します。よろしいですか？"
        ):
            return
        try:
            self.apply_rule_settings(RuleSettings(), source="リセット")
        except Exception as e:
            logger.error(f"設定リセット中にエラー: {e}", exc_info=True)
            self.add_log(f"設定リセットエラー: {e}", "error")
```

`_on_calibration_completed` を以下に置き換える:

```python
    def _on_calibration_completed(self, calibration_result):
        """キャリブレーション完了時のコールバック"""
        try:
            confidence = calibration_result.confidence_scores.get("total_confidence", 0)
            self.apply_rule_settings(
                calibration_result.optimal_settings, source="キャリブレーション"
            )
            self.add_log(
                f"キャリブレーション結果を適用しました (信頼度: {confidence:.1%})",
                "success",
            )
        except Exception as e:
            logger.error(f"キャリブレーション結果適用エラー: {e}", exc_info=True)
            self.add_log(f"キャリブレーション結果適用エラー: {e}", "error")
```

`_log_calibration_changes` と `_apply_settings_to_ui` メソッドは丸ごと削除する（`apply_rule_settings` と `_update_rule_settings_ui` に統合済み）。

`src/snoreguard/calibration_modal.py` の `_display_calibration_changes` を以下に置き換える（`field_names` 辞書の複製を排除）:

```python
    def _display_calibration_changes(self):
        """キャリブレーション変更内容を表示"""
        try:
            if not self.original_settings or not self.calibration_result:
                return
            from core.settings import format_setting_value

            new_settings = self.calibration_result.optimal_settings.sanitized()
            confidence = self.calibration_result.confidence_scores.get(
                "total_confidence", 0
            )
            result_text = f"統計的最適化完了 (信頼度: {confidence:.1%})\n\n"
            result_text += "=== 変更された設定値 ===\n"
            changes = self.original_settings.diff(new_settings)
            for _name, label, old, new in changes:
                result_text += (
                    f"{label}:\n  {format_setting_value(old)} → "
                    f"{format_setting_value(new)}\n\n"
                )
            if not changes:
                result_text += "変更された設定項目はありません\n"
            result_text += "========================"

            self.result_text.configure(state="normal")
            self.result_text.delete("1.0", "end")
            self.result_text.insert("1.0", result_text)
            self.result_text.configure(state="disabled")
        except Exception as e:
            logger.error(f"変更内容表示エラー: {e}", exc_info=True)
```

- [x] **Step 4: テストと import スモーク**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.calibration_modal; print('import ok')"`
Expected: 全 PASS、`import ok`。`grep -n "self.rule_settings = " src/snoreguard/app.py` の結果が `__init__` の 1 箇所のみであること。

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/app.py src/snoreguard/calibration_modal.py tests/test_settings_sharing.py
git commit -m "fix: リセット/キャリブレーション適用時に RuleSettings を差し替えず copy_from で検出器と共有し、スライダーの相互制約を適用"
```

---

### Task 7: 特徴量フォールバックの廃止とチャンクスキップ（検出スレッドが落ちない）

**Files:**
- Modify: `src/core/rule_processor.py:41-117, 303-334`
- Test: `tests/test_rule_processor_errors.py`

**Interfaces:**
- Produces: `core.rule_processor.FeatureExtractionError(RuntimeError)`; `RuleBasedProcessor.process_audio_chunk()` は特徴量抽出に失敗したとき **例外を出さず `{}` を返す**。

- [x] **Step 1: 失敗するテストを書く**

`tests/test_rule_processor_errors.py`:

```python
import numpy as np
import pytest

from core.rule_processor import FeatureExtractionError, FeatureExtractor, RuleBasedProcessor
from core.settings import RuleSettings


def test_feature_extractor_raises_on_invalid_f0_range():
    fe = FeatureExtractor(16000, 800, 200, RuleSettings(f0_min_hz=150, f0_max_hz=100))
    with pytest.raises(FeatureExtractionError):
        fe.extract_features(np.zeros(16000, dtype=np.float32))


def test_process_audio_chunk_skips_chunk_instead_of_crashing():
    # sanitized を通さない生の不正値（JSON 手編集などを想定）
    settings = RuleSettings(f0_min_hz=150, f0_max_hz=100)
    processor = RuleBasedProcessor(settings, lambda: None)
    result = processor.process_audio_chunk(np.zeros(16000, dtype=np.float32))
    assert result == {}


def test_process_audio_chunk_returns_81_frames_for_one_second():
    processor = RuleBasedProcessor(RuleSettings(), lambda: None)
    result = processor.process_audio_chunk(np.zeros(16000, dtype=np.float32))
    assert len(result["final_mask_frames"]) == 81
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_rule_processor_errors.py -q`
Expected: ImportError（`FeatureExtractionError` なし）

- [x] **Step 3: 実装**

`src/core/rule_processor.py` の `FeatureExtractor` クラス全体を以下に置き換える（`_fallback_*` は削除）:

```python
class FeatureExtractionError(RuntimeError):
    """特徴量抽出に失敗した（このチャンクはスキップする）"""


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
        """全特徴量を一括抽出。失敗時は FeatureExtractionError。

        すべての配列は同じフレーム数（1 + len(audio) // hop_length）で返る。
        旧実装の固定 20 フレームのフォールバックは形状不整合で検出スレッドを
        落としていたため廃止した。
        """
        try:
            f0, _voiced_flag, voiced_probs = librosa.pyin(
                y=audio_chunk,
                fmin=self.settings.f0_min_hz,
                fmax=self.settings.f0_max_hz,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
                sr=self.sample_rate,
            )
            return {
                "rms": librosa.feature.rms(
                    y=audio_chunk,
                    frame_length=self.frame_length,
                    hop_length=self.hop_length,
                )[0],
                "spectral_centroid": librosa.feature.spectral_centroid(
                    y=audio_chunk,
                    sr=self.sample_rate,
                    n_fft=self.frame_length,
                    hop_length=self.hop_length,
                )[0],
                "zcr": librosa.feature.zero_crossing_rate(
                    y=audio_chunk,
                    frame_length=self.frame_length,
                    hop_length=self.hop_length,
                )[0],
                "f0": np.nan_to_num(f0, nan=0.0),
                "voiced_probs": voiced_probs,
            }
        except Exception as e:
            raise FeatureExtractionError(str(e)) from e
```

`RuleBasedProcessor._warmup_librosa` はそのまま（例外は握る）。`process_audio_chunk` の先頭部分を以下に変更:

```python
    def process_audio_chunk(self, audio_chunk: np.ndarray) -> Dict[str, Any]:
        """音声チャンクの処理。特徴量抽出に失敗したチャンクは {} を返してスキップ"""
        filtered_chunk = sosfilt(self.sos_filter, audio_chunk, axis=0)

        try:
            features = self.feature_extractor.extract_features(filtered_chunk)
        except FeatureExtractionError as e:
            logger.warning(f"特徴量抽出に失敗したためチャンクをスキップ: {e}")
            return {}
```

（`if not features: return {}` の行は削除。以降は既存どおり。）

- [x] **Step 4: テスト**

Run: `uv run --no-sync pytest tests/test_rule_processor_errors.py -q`
Expected: `3 passed`

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/core/rule_processor.py tests/test_rule_processor_errors.py
git commit -m "fix: 形状不整合を起こす特徴量フォールバックを廃止し、抽出失敗チャンクはスキップする"
```

---

### Task 8: 音声ストリーム停止の App への伝播・自動再開・無音ウォッチドッグ

**Files:**
- Modify: `src/snoreguard/audio_service.py`（`__init__`, `_detection_loop`）
- Modify: `src/snoreguard/app.py`（`__init__`, `_finalize_detection_start`, `_stop_detection`, `_process_analysis_data`、新規メソッド）
- Test: `tests/test_audio_service.py`

**Interfaces:**
- Produces:
  - `AudioService.__init__(..., on_stream_stopped: Callable[[str | None], None] | None = None)`。ワーカー終了時に `on_stream_stopped(error)` を **ワーカースレッドから** 1 回呼ぶ（正常停止は `None`、異常終了はメッセージ）。
  - `AudioService.last_error: str | None`
  - `SnoreGuardApp._on_audio_stream_stopped(error)`（スレッド → safe_after）、`SnoreGuardApp._handle_stream_stopped(error)`（メインスレッド）、`SnoreGuardApp.RESTART_DELAYS_S = (5, 10, 20, 40, 60)`

- [x] **Step 1: 失敗するテストを書く**

`tests/test_audio_service.py`:

```python
import queue
import threading

import numpy as np
import pytest

import snoreguard.audio_service as audio_service_module
from core.settings import RuleSettings
from snoreguard.audio_service import AudioService


class _FakeStream:
    """読み取りで例外を投げる sd.InputStream の代替"""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, frames):
        raise RuntimeError("PortAudio device lost")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(audio_service_module.sd, "InputStream", _FakeStream)
    monkeypatch.setattr(
        audio_service_module.sd,
        "query_devices",
        lambda: [{"name": "fake", "max_input_channels": 1}],
    )
    stopped = []
    done = threading.Event()

    def on_stopped(error):
        stopped.append(error)
        done.set()

    svc = AudioService(
        RuleSettings(),
        queue.Queue(maxsize=5),
        snore_detected_callback=lambda: None,
        log_callback=lambda msg, level="info": None,
        on_stream_stopped=on_stopped,
    )
    return svc, stopped, done


def test_stream_error_is_reported_via_callback(service):
    svc, stopped, done = service
    svc.start(0)
    assert done.wait(timeout=5)
    assert stopped and "device lost" in stopped[0]
    assert svc.is_running is False
    assert "device lost" in (svc.last_error or "")


def test_normal_stop_reports_none(monkeypatch):
    class _OkStream(_FakeStream):
        def read(self, frames):
            return np.zeros((frames, 1), dtype=np.float32), False

    monkeypatch.setattr(audio_service_module.sd, "InputStream", _OkStream)
    monkeypatch.setattr(
        audio_service_module.sd,
        "query_devices",
        lambda: [{"name": "fake", "max_input_channels": 1}],
    )
    stopped = []
    done = threading.Event()
    svc = AudioService(
        RuleSettings(),
        queue.Queue(maxsize=5),
        snore_detected_callback=lambda: None,
        log_callback=lambda msg, level="info": None,
        on_stream_stopped=lambda e: (stopped.append(e), done.set()),
    )
    svc.start(0)
    svc.stop()
    assert done.wait(timeout=5)
    assert stopped == [None]
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_audio_service.py -q`
Expected: TypeError（`on_stream_stopped` 引数なし）

- [x] **Step 3: AudioService を実装**

`__init__` のシグネチャと本体に追加:

```python
    def __init__(
        self,
        rule_settings,
        data_queue,
        snore_detected_callback: Callable[[], None],
        log_callback: Callable[[str, str], None],
        on_stream_stopped: Callable[[str | None], None] | None = None,
    ):
        ...
        self.on_stream_stopped = on_stream_stopped  # ワーカー終了通知
        self.last_error: str | None = None  # 直近の異常終了メッセージ
```

`start()` の `self.is_running = True` の直前に `self.last_error = None` を追加。

`_detection_loop` を以下に置き換える:

```python
    def _detection_loop(self, device_id: int):
        """音声入力と処理のメインループ（ワーカースレッド）"""
        logger.debug(f"検出ループ開始 - device_id: {device_id}")
        error_message: str | None = None
        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                device=device_id,
                channels=1,
                dtype="float32",
                blocksize=self.VIZ_CHUNK_SIZE,
            ) as self.stream:
                logger.info(
                    f"オーディオストリーム開始 - device: {device_id}, SR: {self.SAMPLE_RATE}"
                )
                self.log_callback("オーディオストリームを開始しました。", "system")
                while self.is_running:
                    self._process_stream_data()
        except Exception as e:
            if self.is_running:
                error_message = str(e)
                logger.error(f"検出ループでエラー発生: {e}", exc_info=True)
        finally:
            logger.info("検出ループ終了")
            self.is_running = False
            self.stream = None
            self.last_error = error_message
            if self.on_stream_stopped:
                try:
                    self.on_stream_stopped(error_message)
                except Exception as e:  # noqa: BLE001 - 通知失敗でスレッドを落とさない
                    logger.error(f"停止通知コールバックでエラー: {e}", exc_info=True)
```

（旧実装の `finally` 内 `self.log_callback("オーディオストリームを停止しました。", "system")` は削除する。停止ログは App 側で出す。Tk を同期呼び出しする `log_callback` をワーカー終了経路から外すことが Phase 2 のスレッド規律の前提になる。）

- [x] **Step 4: App 側を配線**

`app.py` `__init__` の `AudioService(...)` 生成に `on_stream_stopped=self._on_audio_stream_stopped,` を追加。`__init__` の状態変数に追加:

```python
        self._restart_attempt = 0  # 音声ストリーム異常終了後の再開試行回数
        self._restart_after_id = None
        self._last_sound_time = None  # 無音ウォッチドッグ用
        self._silence_warned = False
```

クラス定数を追加（`SnoreGuardApp` の先頭）:

```python
    RESTART_DELAYS_S = (5, 10, 20, 40, 60)  # 異常終了後の自動再開の待ち時間
    SILENCE_WARN_AFTER_S = 60  # この秒数 RMS がゼロなら警告
```

新規メソッド（`_stop_detection` の直前に追加）:

```python
    def _on_audio_stream_stopped(self, error: str | None):
        """音声ワーカー終了通知（ワーカースレッドから呼ばれる）"""
        ThreadSafeHandler.safe_after(self.root, self._handle_stream_stopped, error)

    def _handle_stream_stopped(self, error: str | None):
        """音声ワーカー終了の後処理（メインスレッド）"""
        self.add_log("オーディオストリームを停止しました。", "system")
        if error is None or not self.is_running:
            return  # 利用者操作による正常停止
        # 異常終了: UI を待機状態へ戻し、自動再開を試みる
        self.is_running = False
        self._update_control_state()
        self.status_label_var.set("音声入力エラー")
        self.add_log(f"音声入力が停止しました: {error}", "error")
        self._send_status_feedback()
        if self._restart_attempt < len(self.RESTART_DELAYS_S):
            delay = self.RESTART_DELAYS_S[self._restart_attempt]
            self._restart_attempt += 1
            self.add_log(
                f"{delay}秒後に再開を試みます ({self._restart_attempt}/{len(self.RESTART_DELAYS_S)})",
                "warning",
            )
            self.status_label_var.set(f"再接続待機中 ({delay}s)")
            self._restart_after_id = self.root.after(
                delay * 1000, self._retry_start_detection
            )
        else:
            self.add_log("自動再開を諦めました。マイクの接続を確認して手動で開始してください。", "error")
            notify.beep(600, 500)

    def _retry_start_detection(self):
        """自動再開（スケジューラ経路と同様に非対話で開始）"""
        self._restart_after_id = None
        if self.is_running or self.is_initializing:
            return
        self._populate_mic_list()  # デバイス一覧を取り直す（抜き差し対応は Phase 2）
        self._start_detection()
```

`_finalize_detection_start` の先頭に `self._restart_attempt = 0` と `self._last_sound_time = datetime.now()`、`self._silence_warned = False` を追加。`_stop_detection` の `self.is_running = False` の直前に:

```python
        if self._restart_after_id:
            self.root.after_cancel(self._restart_after_id)
            self._restart_after_id = None
        self._restart_attempt = 0
```

`_process_analysis_data` の末尾（`self._update_detailed_status(res)` の後）に無音ウォッチドッグを追加:

```python
        self._check_silence(res)

    def _check_silence(self, res: dict):
        """一定時間 RMS がゼロなら、マイクが無音であることを知らせる"""
        results = res.get("analysis_results") or {}
        rms = results.get("rms")
        now = datetime.now()
        if rms is not None and len(rms) > 0 and float(np.max(rms)) > 1e-6:
            self._last_sound_time = now
            if self._silence_warned:
                self._silence_warned = False
                self.add_log("音声入力を再び検知しました。", "system")
            return
        if self._last_sound_time is None:
            self._last_sound_time = now
            return
        if (
            not self._silence_warned
            and (now - self._last_sound_time).total_seconds() > self.SILENCE_WARN_AFTER_S
        ):
            self._silence_warned = True
            self.add_log(
                "60秒以上無音です。マイクの接続と Windows のマイクのプライバシー設定を確認してください。",
                "warning",
            )
            self.status_label_var.set("⚠ 無音が続いています")
```

- [x] **Step 5: テストと import スモーク**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app; print('import ok')"`
Expected: 全 PASS、`import ok`

- [x] **Step 6: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/audio_service.py tests/test_audio_service.py
git add -p src/snoreguard/app.py   # on_stream_stopped 配線・_handle_stream_stopped・_retry_start_detection・RESTART_DELAYS_S のハンクだけ選ぶ
git commit -m "fix: 音声ストリームの異常終了を App に伝播して UI を待機状態に戻し、段階的に自動再開する"
git add src/snoreguard/app.py      # 残り（_check_silence と SILENCE_WARN_AFTER_S、_last_sound_time 初期化）
git commit -m "feat: 60秒以上の無音を検知して警告する無音ウォッチドッグを追加"
```

（`git add -p` でハンクを分けられない場合は 1 コミットにまとめてよい。その場合のメッセージは 1 つ目を使う。）

---

### Task 9: ミュート判断ポリシー・受信ポート失敗の可視化・単一起動

**Files:**
- Create: `src/snoreguard/mute_policy.py`
- Modify: `src/snoreguard/vrc/handler.py:25-60, 140-146`（`VRChatOSCReceiver.start` と `VRCHandler.start`）
- Modify: `src/snoreguard/app.py`（`_trigger_vrchat_mute`, `_update_internal_mute_state`, `__init__` の VRC 開始部）
- Modify: `src/main.py`（単一起動）
- Create: `src/snoreguard/single_instance.py`
- Test: `tests/test_mute_policy.py`, `tests/test_osc_receiver.py`

**Interfaces:**
- Produces:
  - `mute_policy.MuteAction`（Enum: `SEND_TOGGLE`, `ALREADY_MUTED`, `UNKNOWN_SKIP`）
  - `mute_policy.decide_mute_action(is_muted: bool | None) -> MuteAction`
  - `VRChatOSCReceiver.start() -> bool`、`VRChatOSCReceiver.bind_error: str | None`
  - `VRCHandler.start() -> bool`（受信開始に成功したか）
  - `single_instance.acquire(name: str = "Local\\SnoreGuard") -> bool`（Windows 以外は常に True）

- [x] **Step 1: 失敗するテストを書く**

`tests/test_mute_policy.py`:

```python
from snoreguard.mute_policy import MuteAction, decide_mute_action


def test_unmuted_sends_toggle():
    assert decide_mute_action(False) is MuteAction.SEND_TOGGLE


def test_muted_does_nothing():
    assert decide_mute_action(True) is MuteAction.ALREADY_MUTED


def test_unknown_state_never_toggles_blindly():
    assert decide_mute_action(None) is MuteAction.UNKNOWN_SKIP
```

`tests/test_osc_receiver.py`:

```python
import socket

from snoreguard.vrc.handler import VRChatOSCReceiver


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_returns_true_and_stop_releases_port():
    port = _free_port()
    receiver = VRChatOSCReceiver(port, app_instance=None, log_callback=None)
    assert receiver.start() is True
    assert receiver.bind_error is None
    receiver.stop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", port))  # 解放されていれば bind できる


def test_start_returns_false_when_port_in_use():
    port = _free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
        blocker.bind(("127.0.0.1", port))
        receiver = VRChatOSCReceiver(port, app_instance=None, log_callback=None)
        assert receiver.start() is False
        assert receiver.bind_error is not None
        assert receiver.is_running is False
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_mute_policy.py tests/test_osc_receiver.py -q`
Expected: ImportError / AssertionError（`start()` が None を返す）

- [x] **Step 3: 実装**

`src/snoreguard/mute_policy.py`:

```python
"""VRChat ミュート操作の判断。

/input/Voice はトグルなので、現在のミュート状態が分からないまま送ると
「ミュート解除」になり得る。状態が既知のときだけ送る。
"""

from enum import Enum


class MuteAction(Enum):
    SEND_TOGGLE = "send_toggle"  # 未ミュート → トグルを送る
    ALREADY_MUTED = "already_muted"  # 既にミュート → 何もしない
    UNKNOWN_SKIP = "unknown_skip"  # 状態不明 → 送らない（盲目トグル禁止）


def decide_mute_action(is_muted: bool | None) -> MuteAction:
    if is_muted is None:
        return MuteAction.UNKNOWN_SKIP
    return MuteAction.ALREADY_MUTED if is_muted else MuteAction.SEND_TOGGLE
```

`src/snoreguard/single_instance.py`:

```python
"""多重起動の防止（Windows の名前付きミューテックス）。"""

import logging
import sys

logger = logging.getLogger(__name__)

_ERROR_ALREADY_EXISTS = 183
_handle = None  # プロセス終了までミューテックスを保持する


def acquire(name: str = "Local\\SnoreGuard") -> bool:
    """このプロセスが唯一のインスタンスなら True。Windows 以外は常に True。"""
    global _handle
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _handle = kernel32.CreateMutexW(None, False, name)
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            logger.warning("SnoreGuard は既に起動しています")
            return False
        return True
    except Exception as e:  # noqa: BLE001 - 判定不能時は起動を妨げない
        logger.warning(f"多重起動チェックに失敗: {e}")
        return True
```

`src/snoreguard/vrc/handler.py` の `VRChatOSCReceiver`:

- `__init__` に `self.bind_error: str | None = None` を追加。
- `start()` を以下に置き換える:

```python
    def start(self) -> bool:
        """OSC メッセージの受信を開始。bind に失敗したら False（ログ＋bind_error）"""
        logger.debug(f"OSC受信開始要求 - port: {self.port}")
        if self.is_running:
            logger.warning("OSC受信既に実行中")
            return True
        self.bind_error = None
        try:
            dispatcher_obj = dispatcher.Dispatcher()
            dispatcher_obj.map("/avatar/parameters/MuteSelf", self._mute_handler)
            dispatcher_obj.map(
                "/avatar/parameters/SnoreGuard/ToggleDetection",
                self._toggle_detection_handler,
            )
            dispatcher_obj.map(
                "/avatar/parameters/SnoreGuard/SetNotification",
                self._set_notification_handler,
            )
            dispatcher_obj.map(
                "/avatar/parameters/SnoreGuard/SetAutoMute", self._set_auto_mute_handler
            )
            self.server = osc_server.ThreadingOSCUDPServer(
                ("127.0.0.1", self.port), dispatcher_obj
            )
        except OSError as e:
            self.bind_error = (
                f"受信ポート {self.port} を開けません（他のアプリが使用中の可能性）: {e}"
            )
            logger.error(self.bind_error)
            if self.log_callback:
                self.log_callback(self.bind_error, "error")
            self.server = None
            return False

        self._server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True, name="osc-receiver"
        )
        self._server_thread.start()
        self.is_running = True
        logger.info(f"OSC受信開始成功 - port: {self.port}")
        if self.log_callback:
            self.log_callback(f"OSC受信: ポート{self.port}で開始", "osc")
        return True
```

- `stop()` の `self.server.shutdown()` の直後に `self.server.server_close()` を追加（ソケット解放）。

`VRCHandler.start()` を以下に置き換える:

```python
    def start(self) -> bool:
        """すべてのVRChat連携サービスを開始。戻り値は OSC 受信が開始できたか"""
        logger.debug("VRCHandler開始")
        self.osc_service.start()
        receiver_ok = self.osc_receiver.start()
        self.oscquery_finder.start()
        logger.info(f"VRCHandler開始完了 (受信: {'OK' if receiver_ok else 'NG'})")
        return receiver_ok
```

`src/snoreguard/app.py`:

- import に `from snoreguard.mute_policy import MuteAction, decide_mute_action` を追加。
- `__init__` の `self.vrc_handler.start()` を次に置き換える:

```python
        self.receiver_ok = self.vrc_handler.start()
        if not self.receiver_ok:
            self.root.after(1200, self._warn_receiver_unavailable)
```

- 新規メソッド:

```python
    def _warn_receiver_unavailable(self):
        """OSC 受信ポートが開けない＝ミュート状態を追跡できないことを明示"""
        message = self.vrc_handler.osc_receiver.bind_error or "OSC 受信を開始できません"
        self.add_log(message, "error")
        self.add_log(
            "VRChat のミュート状態を受信できないため、自動ミュートは送信されません。"
            "VRCFaceTracking など 9001 番ポートを使うアプリを終了して再起動してください。",
            "warning",
        )
        self.status_label.configure(fg_color="#E74C3C")
        self.status_label_var.set("受信ポート 9001 が使用中")
```

- `_trigger_vrchat_mute` を以下に置き換える（探りトグルを廃止）:

```python
    def _trigger_vrchat_mute(self):
        """VRChatミュート処理。状態不明なら送らない（盲目トグルはミュート解除になり得る）"""
        action = decide_mute_action(self.is_vrchat_muted)
        logger.debug(f"VRChatミュート判断: {action.value} (現在状態={self.is_vrchat_muted})")
        if action is MuteAction.SEND_TOGGLE:
            self.add_log("VRChatマイクをミュートします。", "osc")
            self.muted_by_snoreguard = True
            self.vrc_handler.toggle_mute()
        elif action is MuteAction.ALREADY_MUTED:
            self.add_log("VRChatは既にミュートです。", "osc")
        else:
            self.add_log(
                "VRChatのミュート状態が不明なため送信しません"
                "（VRChatからMuteSelfを受信できていません）。",
                "warning",
            )
```

- `__init__` の状態変数に `self.muted_by_snoreguard = False` を追加し、`is_awaiting_mute_sync` / `sync_timeout_id` の初期化行、`_cancel_mute_sync_timeout` メソッドは削除。`_update_internal_mute_state` を以下に置き換える:

```python
    def _update_internal_mute_state(self, is_muted: bool):
        """VRChat から受信したミュート状態を内部状態に反映"""
        if self.is_vrchat_muted is None:
            self.add_log(
                f"VRChatのミュート状態を同期しました: {'ミュート' if is_muted else 'ミュート解除'}",
                "vrchat",
            )
        self.is_vrchat_muted = is_muted
        if not is_muted:
            self.muted_by_snoreguard = False
```

`src/main.py` の `main()` 冒頭（`splash = QuickSplashScreen()` の前）に追加:

```python
    from snoreguard.single_instance import acquire

    if not acquire():
        show_fatal_error("SnoreGuard は既に起動しています。")
        return 1
```

- [x] **Step 4: テストと import スモーク**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import main; print('import ok')"`
Expected: 全 PASS、`import ok`。`grep -n "is_awaiting_mute_sync\|sync_timeout_id" src/snoreguard/app.py` が空であること。

- [x] **Step 5: コミット（3 つ）**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/mute_policy.py src/snoreguard/app.py tests/test_mute_policy.py
git commit -m "fix: ミュート状態が不明なときの探りトグルを廃止し、既知のときだけ /input/Voice を送る"
git add src/snoreguard/vrc/handler.py tests/test_osc_receiver.py
git commit -m "fix: OSC 受信ポートの bind 失敗を戻り値で伝え、UI に赤表示で警告"
git add src/snoreguard/single_instance.py src/main.py
git commit -m "feat: 名前付きミューテックスで多重起動を防止"
```

（`app.py` の変更が 1・2 番目のコミットにまたがる場合は `git add -p` で分ける。分けられなければ 1・2 を 1 コミットにまとめてよい。）

---

### Task 10: 検出ロジック — チャンク跨ぎセグメント・サンプルクロック・イベント間隔・フィルタ状態

**Files:**
- Modify: `src/core/rule_processor.py`（`SegmentProcessor` 全体、`RuleBasedProcessor.__init__/reset_periodicity/process_audio_chunk/_check_periodicity`）
- Test: `tests/test_segment_processor.py`, `tests/test_periodicity.py`, `tests/test_bandpass_state.py`

**Interfaces:**
- Produces:
  - `SegmentProcessor.process_segments(final_mask: np.ndarray, features: dict, chunk_start: datetime) -> list[SnoreEvent]`（開いたままのセグメントは次チャンクへ持ち越す）、`SegmentProcessor.reset()`
  - `RuleBasedProcessor.__init__(settings, callback, clock: Callable[[], datetime] = datetime.now)`
  - `RuleBasedProcessor.process_audio_chunk(audio_chunk, chunk_start: datetime | None = None)`
  - `RuleBasedProcessor.register_event(event: SnoreEvent) -> None`（間隔検証＋周期性判定。テスト用に公開）

- [x] **Step 1: 失敗するテストを書く**

`tests/test_segment_processor.py`:

```python
from datetime import datetime, timedelta

import numpy as np

from core.rule_processor import SegmentProcessor
from core.settings import RuleSettings

SR, HOP = 16000, 200
FRAME_DT = HOP / SR  # 0.0125 s
T0 = datetime(2026, 1, 1, 0, 0, 0)


def _feats(n):
    return {
        "rms": np.full(n, 0.05, dtype=np.float32),
        "f0": np.full(n, 100.0, dtype=np.float32),
    }


def _mask(n, true_ranges):
    m = np.zeros(n, dtype=bool)
    for a, b in true_ranges:
        m[a:b] = True
    return m


def test_segment_inside_one_chunk():
    sp = SegmentProcessor(HOP, SR, RuleSettings(min_duration_seconds=0.2, max_duration_seconds=3.0))
    events = sp.process_segments(_mask(81, [(10, 40)]), _feats(81), T0)
    assert len(events) == 1
    assert abs(events[0].duration - 30 * FRAME_DT) < 1e-9
    assert events[0].timestamp == T0 + timedelta(seconds=10 * FRAME_DT)


def test_segment_spanning_two_chunks_is_one_event():
    sp = SegmentProcessor(HOP, SR, RuleSettings())
    first = sp.process_segments(_mask(81, [(60, 81)]), _feats(81), T0)
    assert first == []  # チャンク末尾まで True → 持ち越し
    second = sp.process_segments(_mask(81, [(0, 20)]), _feats(81), T0 + timedelta(seconds=1))
    assert len(second) == 1
    assert abs(second[0].duration - (21 + 20) * FRAME_DT) < 1e-9
    assert second[0].timestamp == T0 + timedelta(seconds=60 * FRAME_DT)


def test_long_continuous_sound_is_rejected_by_max_duration():
    sp = SegmentProcessor(HOP, SR, RuleSettings(max_duration_seconds=3.0))
    all_true = _mask(81, [(0, 81)])
    for i in range(4):  # 4 秒連続
        assert sp.process_segments(all_true, _feats(81), T0 + timedelta(seconds=i)) == []
    closing = sp.process_segments(_mask(81, [(0, 5)]), _feats(81), T0 + timedelta(seconds=4))
    assert closing == []  # 合計 > 3 秒なので棄却


def test_too_short_segment_is_rejected():
    sp = SegmentProcessor(HOP, SR, RuleSettings(min_duration_seconds=0.2))
    assert sp.process_segments(_mask(81, [(0, 5)]), _feats(81), T0) == []


def test_reset_drops_open_segment():
    sp = SegmentProcessor(HOP, SR, RuleSettings())
    sp.process_segments(_mask(81, [(60, 81)]), _feats(81), T0)
    sp.reset()
    assert sp.process_segments(_mask(81, [(0, 5)]), _feats(81), T0 + timedelta(seconds=1)) == []
```

`tests/test_periodicity.py`:

```python
from datetime import datetime, timedelta

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings, SnoreEvent

T0 = datetime(2026, 1, 1, 0, 0, 0)


def _proc(**kw):
    hits = []
    settings = RuleSettings(
        periodicity_event_count=4,
        periodicity_window_seconds=45,
        min_event_interval_seconds=2.0,
        max_event_interval_seconds=10.0,
        **kw,
    )
    proc = RuleBasedProcessor(settings, lambda: hits.append(1), clock=lambda: T0)
    return proc, hits


def _ev(sec):
    return SnoreEvent(timestamp=T0 + timedelta(seconds=sec), duration=0.5)


def test_four_regular_snores_fire_once():
    proc, hits = _proc()
    for t in (0, 4, 8, 12):
        proc.register_event(_ev(t))
    assert hits == [1]
    assert len(proc.recent_events) == 0  # 発火後はクリア


def test_bursts_within_min_interval_count_as_one():
    proc, hits = _proc()
    for t in (0, 0.3, 0.6, 0.9):  # 1 秒内の 4 バースト
        proc.register_event(_ev(t))
    assert hits == []
    assert len(proc.recent_events) == 1


def test_gap_longer_than_max_interval_resets_sequence():
    proc, hits = _proc()
    for t in (0, 4, 8):
        proc.register_event(_ev(t))
    proc.register_event(_ev(30))  # 22 秒空いた → 周期列リセット
    assert hits == []
    assert len(proc.recent_events) == 1


def test_events_outside_window_are_dropped():
    proc, hits = _proc()
    proc.register_event(_ev(0))
    proc.register_event(_ev(5))
    proc.register_event(_ev(60))  # max_interval を超えるのでリセットされる
    assert len(proc.recent_events) == 1
```

`tests/test_bandpass_state.py`:

```python
import numpy as np

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings


def test_filter_state_carries_across_chunks():
    sr = 16000
    t = np.arange(sr * 2) / sr
    signal = (0.3 * np.sin(2 * np.pi * 100 * t)).astype(np.float32)
    proc = RuleBasedProcessor(RuleSettings(), lambda: None)
    assert not np.any(proc._zi)  # 初期状態はゼロ
    r1 = proc.process_audio_chunk(signal[:sr])
    assert np.any(proc._zi)  # 1 チャンク処理後は状態が残る
    r2 = proc.process_audio_chunk(signal[sr:])
    rms1 = r1["analysis_results"]["rms"]
    rms2 = r2["analysis_results"]["rms"]
    # フレーム 2（サンプル 0..800、端のゼロ埋めを含まない）が定常値に近いこと。
    # 状態を引き継がない旧実装では過渡応答で約 0.91 倍に落ちる。
    assert rms2[2] > 0.95 * np.median(rms1[10:70])


def test_reset_clears_filter_state():
    proc = RuleBasedProcessor(RuleSettings(), lambda: None)
    proc.process_audio_chunk(np.random.default_rng(0).normal(0, 0.1, 16000).astype(np.float32))
    proc.reset_periodicity()
    assert not np.any(proc._zi)
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_segment_processor.py tests/test_periodicity.py tests/test_bandpass_state.py -q`
Expected: TypeError（`process_segments` の引数数、`clock` 引数、`register_event` なし）

- [x] **Step 3: `SegmentProcessor` を実装**

`src/core/rule_processor.py` の `SegmentProcessor` クラス全体を以下に置き換える:

```python
class SegmentProcessor:
    """final_mask の連続 True 区間をいびき候補イベントにする。

    1 秒チャンクごとに呼ばれるが、チャンク末尾まで True の区間は「開いたまま」
    次のチャンクへ持ち越す。これにより max_duration（長すぎる連続音の棄却）が
    本来の意味で機能し、境界で分断された 1 回のいびきも 1 イベントになる。
    """

    def __init__(self, hop_length: int, sample_rate: int, settings: RuleSettings):
        self.hop_length = hop_length
        self.sample_rate = sample_rate
        self.settings = settings
        self.frame_seconds = hop_length / sample_rate
        self.reset()

    def reset(self):
        """持ち越し中のセグメントを破棄"""
        self._open_frames = 0
        self._open_start: datetime | None = None
        self._open_rms: list[float] = []
        self._open_f0: list[float] = []
        self._open_too_long = False

    def process_segments(
        self, final_mask: np.ndarray, features: Dict[str, np.ndarray], chunk_start: datetime
    ) -> list:
        """チャンク内のマスクを走査し、閉じたセグメントからイベントを作る"""
        events = []
        n = len(final_mask)
        i = 0

        if self._open_frames > 0:
            # 前チャンクから継続中のセグメント
            j = 0
            while j < n and final_mask[j]:
                j += 1
            self._extend_open(features, 0, j)
            if j >= n:
                return events  # まだ閉じていない
            event = self._close_open()
            if event:
                events.append(event)
            i = j

        while i < n:
            if not final_mask[i]:
                i += 1
                continue
            j = i
            while j < n and final_mask[j]:
                j += 1
            self._open_start = chunk_start + timedelta(seconds=i * self.frame_seconds)
            self._extend_open(features, i, j)
            if j >= n:
                break  # チャンク末尾まで True → 持ち越し
            event = self._close_open()
            if event:
                events.append(event)
            i = j

        return events

    def _extend_open(self, features: Dict[str, np.ndarray], start: int, end: int):
        """開いているセグメントにフレーム [start, end) を追加"""
        count = end - start
        if count <= 0:
            return
        self._open_frames += count
        if self._open_frames * self.frame_seconds > self.settings.max_duration_seconds:
            # 長すぎる連続音: 以降の統計は捨て、閉じたときに棄却する
            self._open_too_long = True
            self._open_rms.clear()
            self._open_f0.clear()
            return
        self._open_rms.extend(float(v) for v in features["rms"][start:end])
        self._open_f0.extend(float(v) for v in features["f0"][start:end])

    def _close_open(self) -> SnoreEvent | None:
        """開いているセグメントを閉じ、持続時間が範囲内ならイベントを返す"""
        duration = self._open_frames * self.frame_seconds
        start = self._open_start
        rms_values = np.array(self._open_rms, dtype=np.float32)
        f0_values = np.array(self._open_f0, dtype=np.float32)
        too_long = self._open_too_long
        self.reset()

        if too_long or start is None:
            return None
        if not (
            self.settings.min_duration_seconds <= duration <= self.settings.max_duration_seconds
        ):
            return None
        valid_f0 = f0_values[f0_values > 0]
        return SnoreEvent(
            timestamp=start,
            duration=duration,
            f0=float(np.mean(valid_f0)) if len(valid_f0) else 0.0,
            energy=float(np.mean(rms_values)) if len(rms_values) else 0.0,
        )
```

- [x] **Step 4: `RuleBasedProcessor` を実装**

import に `from scipy.signal import butter, sosfilt, sosfilt_zi` を使う。`__init__` のシグネチャを `def __init__(self, settings: RuleSettings, callback: Callable[[], None], clock: Callable[[], datetime] = datetime.now):` にし、`self.sos_filter = butter(...)` の**直後**（`self.feature_extractor = ...` より前）に追加:

```python
        self.clock = clock
        self._zi = sosfilt_zi(self.sos_filter) * 0.0  # 帯域通過フィルタの内部状態 (n_sections, 2)
```

（`_warmup_librosa` は `extract_features` を直接呼ぶため `_zi` を汚さない。）

`reset_periodicity` を以下に置き換える:

```python
    def reset_periodicity(self):
        """周期性イベントキュー・持ち越しセグメント・フィルタ状態をリセット"""
        self.recent_events.clear()
        self.segment_processor.reset()
        self._zi[...] = 0.0
        logger.debug("周期性イベントキューがリセットされました。")
```

`process_audio_chunk` を以下に置き換える:

```python
    def process_audio_chunk(
        self, audio_chunk: np.ndarray, chunk_start: datetime | None = None
    ) -> Dict[str, Any]:
        """音声チャンクの処理。特徴量抽出に失敗したチャンクは {} を返してスキップ"""
        if chunk_start is None:
            chunk_start = self.clock() - timedelta(seconds=len(audio_chunk) / self.sample_rate)

        filtered_chunk, self._zi = sosfilt(self.sos_filter, audio_chunk, zi=self._zi)

        try:
            features = self.feature_extractor.extract_features(filtered_chunk)
        except FeatureExtractionError as e:
            logger.warning(f"特徴量抽出に失敗したためチャンクをスキップ: {e}")
            return {}

        features = self._limit_frame_count(features)
        pass_masks, final_mask = self.mask_processor.create_masks(features)

        events = self.segment_processor.process_segments(final_mask, features, chunk_start)
        for event in events:
            self.register_event(event)

        return {
            "analysis_results": features,
            "pass_masks": {k: v.copy() for k, v in pass_masks.items()},
            "final_mask_frames": final_mask,
            "recent_events_count": len(self.recent_events),
            "first_event_timestamp": self.recent_events[0].timestamp
            if self.recent_events
            else None,
        }

    def register_event(self, event: SnoreEvent) -> None:
        """イベントを周期列に登録し、間隔条件と周期性条件を評価する"""
        s = self.settings
        if self.recent_events:
            gap = (event.timestamp - self.recent_events[-1].timestamp).total_seconds()
            if gap < s.min_event_interval_seconds:
                logger.debug(f"イベント間隔 {gap:.2f}s が短すぎるため同一イベントとして無視")
                return
            if gap > s.max_event_interval_seconds:
                logger.debug(f"イベント間隔 {gap:.2f}s が長すぎるため周期列をリセット")
                self.recent_events.clear()
        self.recent_events.append(event)
        self._check_periodicity(event.timestamp)

    def _check_periodicity(self, now: datetime):
        """周期ウィンドウ内のイベント数が閾値に達したら検出コールバックを呼ぶ"""
        window_start = now - timedelta(seconds=self.settings.periodicity_window_seconds)
        while self.recent_events and self.recent_events[0].timestamp < window_start:
            self.recent_events.popleft()
        if len(self.recent_events) >= self.settings.periodicity_event_count:
            logger.info(
                f"いびき検知成功！周期ウィンドウ内に{len(self.recent_events)}回のイベントを検出"
            )
            self.on_snore_detected()
            self.recent_events.clear()
```

`_calculate_detailed_stats` メソッドは戻り値が捨てられていたので削除する（呼び出しも削除済み）。

- [x] **Step 5: テスト（全体）**

Run: `uv run --no-sync pytest -q`
Expected: 全 PASS（`test_process_audio_chunk_returns_81_frames_for_one_second` を含む）

- [x] **Step 6: コミット（3 つ）**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/core/rule_processor.py tests/test_segment_processor.py
git commit -m "fix: セグメント化をチャンク跨ぎの状態機械にし、最大持続時間で長い連続音を棄却する"
git add tests/test_periodicity.py
git commit -m "fix: イベント間隔（min/max_event_interval_seconds）を周期性判定に反映し、タイムスタンプをサンプルクロックに"
git add tests/test_bandpass_state.py
git commit -m "fix: 帯域通過フィルタの状態をチャンク間で引き継ぐ（sosfilt_zi）"
```

（`rule_processor.py` の変更は 1 つ目のコミットに含まれる。テストの分割で履歴の意図を残す。）

---

### Task 11: pyin の広帯域化（F0 範囲ルールを意味のあるものにする）

**Files:**
- Create: `src/core/constants.py`
- Modify: `src/core/rule_processor.py`（`FeatureExtractor.extract_features` の pyin 引数、`RuleBasedProcessor.__init__` の定数）
- Test: `tests/test_f0_range.py`

**Interfaces:**
- Produces（`core.constants`）: `SAMPLE_RATE = 16000`, `FRAME_LENGTH = 800`, `HOP_LENGTH = 200`, `PYIN_FMIN_HZ = 50.0`, `PYIN_FMAX_HZ = 450.0`, `BANDPASS_HZ = (80, 1600)`, `ANALYSIS_CHUNK_SECONDS = 1.0`

- [x] **Step 1: 失敗するテストを書く**

`tests/test_f0_range.py`:

```python
import numpy as np

from core.rule_processor import RuleBasedProcessor
from core.settings import RuleSettings


def _tone(freq, sr=16000, sec=1.0, amp=0.3):
    t = np.arange(int(sr * sec)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_high_pitch_is_measured_outside_snore_range():
    proc = RuleBasedProcessor(RuleSettings(f0_min_hz=70, f0_max_hz=150), lambda: None)
    proc.process_audio_chunk(_tone(440))  # フィルタ状態を温める
    res = proc.process_audio_chunk(_tone(440))
    f0 = res["analysis_results"]["f0"]
    voiced = f0[f0 > 0]
    assert len(voiced) > 0
    assert np.median(voiced) > 300  # 旧実装では 146Hz に折り返していた
    assert not res["pass_masks"]["f0_range"].any()


def test_low_pitch_is_inside_range():
    proc = RuleBasedProcessor(RuleSettings(f0_min_hz=70, f0_max_hz=150), lambda: None)
    proc.process_audio_chunk(_tone(100))
    res = proc.process_audio_chunk(_tone(100))
    f0 = res["analysis_results"]["f0"]
    voiced = f0[f0 > 0]
    assert abs(np.median(voiced) - 100) < 10
    assert res["pass_masks"]["f0_range"].mean() > 0.8
```

- [x] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_f0_range.py -q`
Expected: `test_high_pitch_is_measured_outside_snore_range` が FAIL（f0 が 150 以下に折り返す）

- [x] **Step 3: 実装**

`src/core/constants.py`:

```python
"""検出エンジンと自動キャリブレーションで共有する信号処理の定数。"""

SAMPLE_RATE = 16000
FRAME_LENGTH = 800  # 50 ms
HOP_LENGTH = 200  # 12.5 ms
ANALYSIS_CHUNK_SECONDS = 1.0
BANDPASS_HZ = (80, 1600)

# pyin の探索範囲。いびきの F0 範囲（設定値）より広く取り、
# 範囲外のピッチがサブハーモニクスとして折り返すのを防ぐ。
PYIN_FMIN_HZ = 50.0
PYIN_FMAX_HZ = 450.0
```

`rule_processor.py`: `from core.constants import BANDPASS_HZ, FRAME_LENGTH, HOP_LENGTH, PYIN_FMAX_HZ, PYIN_FMIN_HZ, SAMPLE_RATE` を追加。`FeatureExtractor.extract_features` の pyin 呼び出しを `fmin=PYIN_FMIN_HZ, fmax=PYIN_FMAX_HZ` に変更（`self.settings.f0_min_hz/f0_max_hz` は使わない。範囲判定は `MaskProcessor` の `f0_range_mask` が担う）。`RuleBasedProcessor.__init__` の `self.sample_rate = 16000` 等を定数参照に:

```python
        self.sample_rate = SAMPLE_RATE
        self.frame_length = FRAME_LENGTH
        self.hop_length = HOP_LENGTH
        ...
        self.sos_filter = butter(
            N=5, Wn=list(BANDPASS_HZ), btype="bandpass", fs=self.sample_rate, output="sos"
        )
```

`tests/test_rule_processor_errors.py` の `test_feature_extractor_raises_on_invalid_f0_range` と `test_process_audio_chunk_skips_chunk_instead_of_crashing` は、pyin が設定値を使わなくなったため成立しなくなる。次のように書き換える（失敗を注入して「スキップする」契約だけを検証する）:

```python
def test_feature_extractor_wraps_errors(monkeypatch):
    import core.rule_processor as rp

    def boom(**kwargs):
        raise ValueError("pyin failed")

    monkeypatch.setattr(rp.librosa, "pyin", boom)
    fe = FeatureExtractor(16000, 800, 200, RuleSettings())
    with pytest.raises(FeatureExtractionError):
        fe.extract_features(np.zeros(16000, dtype=np.float32))


def test_process_audio_chunk_skips_chunk_instead_of_crashing(monkeypatch):
    import core.rule_processor as rp

    processor = RuleBasedProcessor(RuleSettings(), lambda: None)

    def boom(**kwargs):
        raise ValueError("pyin failed")

    monkeypatch.setattr(rp.librosa, "pyin", boom)
    assert processor.process_audio_chunk(np.zeros(16000, dtype=np.float32)) == {}
```

- [x] **Step 4: テスト**

Run: `uv run --no-sync pytest -q`
Expected: 全 PASS

- [x] **Step 5: コミット**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/core/constants.py src/core/rule_processor.py tests/test_f0_range.py tests/test_rule_processor_errors.py
git commit -m "fix: pyin を 50-450Hz の広帯域で実行し、F0 範囲は後段のマスクで判定する"
```

---

### Task 12: Phase 1 の仕上げ — 手動スモークと計画の更新

**Files:**
- Modify: `docs/superpowers/plans/2026-08-23-windows-refresh-phase1.md`（チェックボックス）

- [x] **Step 1: 全テストと lint**

Run: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync pytest -q`
Expected: すべて成功。

- [x] **Step 2: import スモーク**

Run: `uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import main, snoreguard.app, snoreguard.ui, snoreguard.calibration_modal; print('import ok')"`
Expected: `import ok`

- [x] **Step 3: GUI スモーク（macOS の場合）**

`TCL_LIBRARY`/`TK_LIBRARY` を uv の Python 3.11.13 の `lib/tcl8.6`・`lib/tk8.6` に設定して `uv run --no-sync python src/main.py` を起動し、ダッシュボードが表示され、ログに「受信ポート」「設定ファイル」系のエラーが出ないことを目視で確認してから終了する。確認できない環境ではスキップしてよい（その旨を報告する）。

- [x] **Step 4: コミット**

```bash
git add docs/superpowers/plans/2026-08-23-windows-refresh-phase1.md
git commit -m "docs: Phase 1 実装計画の進捗を更新"
```
