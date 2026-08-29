# SnoreGuard Windows 版改修 — Phase 3 実装計画（構造・依存・配布・磨き込み）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 監査の P2 項目——lint 規律、デバイス列挙の単純化、librosa 依存の排除（依存面積・起動時間・ライセンス義務の同時解消）、onedir 配布とリリースパイプライン、UI 負荷と運用面の磨き込み——を完了し、Windows 版を配布できる状態にする。

**Architecture:** (1) 特徴量計算を `core/features.py`（numpy/scipy のみ）に置き換え、librosa 版との等価性テストを先に用意してから切り替える。F0 は YIN（CMNDF）で求め、信頼度は `1 - CMNDF 最小値` に置き換える（設定スキーマ version 3 で閾値を既定値に戻す）。(2) デバイス列挙は純粋関数 `devices.list_input_devices` に切り出し、ホスト API を 1 つに固定する。(3) 配布は onedir + zip、タグ push で CI がビルド・チェックサム・provenance を付ける。

**Tech Stack:** Phase 1/2 と同じ。librosa は本 Phase で依存から外れる。

**Spec:** `docs/superpowers/specs/2026-08-23-windows-refresh-audit.md`（課題 15・16）

## 実行状況（2026-08-23 時点）

**未着手。** Phase 1（Task 9〜12 残）と Phase 2 を完了させてから着手すること。

## Global Constraints

Phase 1 計画の Global Constraints を適用する。加えて:

- Task 25（librosa 置換）は **等価性テストが通るまで `FeatureExtractor` を切り替えない**。切り替え後に `uv.lock` から librosa/numba/llvmlite/scikit-learn/soundfile/soxr が消えることを確認する。
- 配布物の見た目（ダッシュボードのレイアウト・文言）は変えない。変えるのは内部構造と描画コストのみ。

---

## ファイル構成（Phase 3 で触るもの）

| ファイル | 責務 | 変更 |
|---|---|---|
| `pyproject.toml` | ruff ルール、依存 | ルール拡張、librosa 削除 |
| `src/snoreguard/devices.py` | **新規** 入力デバイス列挙（純粋関数） | |
| `src/core/features.py` | **新規** numpy/scipy 特徴量 | |
| `src/core/rule_processor.py` | 検出エンジン | `FeatureExtractor` を `core.features` に切り替え |
| `src/core/settings.py` | 設定 | F0 信頼度の既定値/範囲、`settings_version` 3 |
| `src/snoreguard/auto_calibrator.py` | キャリブレーション | librosa import 削除（Phase 2 で済）、warmup 不要 |
| `SnoreGuard.spec`, `scripts/build.bat`, `scripts/gen_third_party_licenses.py`, `.github/workflows/release.yml` | 配布 | onedir、ライセンス一覧、リリース |
| `src/snoreguard/app.py`, `src/snoreguard/ui.py` | UI | デバイス更新ボタン、描画の軽量化、ログ上限/色、スライダー常時有効 |
| `src/snoreguard/settings_manager.py` | 設定 | 旧パスからの移行 |
| `tests/` | テスト | 各タスク |

---

### Task 23: ruff ルールの拡張と機械的修正

**Files:**
- Modify: `pyproject.toml`（`[tool.ruff.lint]`）
- Modify: ruff が指摘する全ファイル（自動修正＋少数の手修正）

- [ ] **Step 1: ルールを拡張する**

`[tool.ruff.lint]` を:

```toml
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "UP", "B", "C4", "SIM", "T20", "RUF100"]
ignore = [
    "SIM108",  # 三項演算子の強制は可読性を落とすことがある
    "B008",    # 引数既定値での関数呼び出し（dataclass field 等）
]
fixable = ["ALL"]
unfixable = []
dummy-variable-rgx = "^(_+|(_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?))$"

[tool.ruff.lint.per-file-ignores]
"src/snoreguard/quick_splash.py" = ["T20"]  # __main__ のデモ用 print
```

- [ ] **Step 2: 自動修正を適用し、残りを手で直す**

Run: `uv run --no-sync ruff check . --fix --unsafe-fixes; uv run --no-sync ruff format .; uv run --no-sync ruff check .`

残る指摘の典型と対処:
- `B904`（except 内の raise に `from e` がない）→ `raise X(...) from e`
- `B007`（未使用ループ変数）→ `_` に改名
- `B905`（`zip` に `strict=`）→ `zip(a, b, strict=False)`
- `T201`（print）→ `logger.info(...)` に置換、または per-file-ignores
- `SIM102/SIM117` などはメッセージどおりに書き換える

`uv run --no-sync ruff check .` が `All checks passed!` になるまで繰り返す。

- [ ] **Step 3: テストとコミット**

Run: `uv run --no-sync pytest -q`
Expected: 全 PASS（挙動は変えていない）

```bash
git add -A src tests pyproject.toml
git commit -m "style: ruff ルールを拡張（I/UP/B/C4/SIM/T20）し自動修正を適用"
```

---

### Task 24: 入力デバイス列挙の純粋関数化・ホスト API 固定・更新ボタン

**Files:**
- Create: `src/snoreguard/devices.py`
- Modify: `src/snoreguard/app.py`（`_populate_mic_list` と `_get_input_devices`〜`_handle_mic_list_error` の置き換え、`refresh_devices`、`_start_detection_async` の extra_settings）
- Modify: `src/snoreguard/audio_service.py`（`start(device_id, extra_settings=None)`）
- Modify: `src/snoreguard/ui.py`（コンボボックス横に「更新」ボタン）
- Test: `tests/test_devices.py`

**Interfaces:**
- Produces（`snoreguard.devices`）:
  - `DEFAULT_DEVICE_LABEL = "既定のデバイス"`
  - `select_hostapi(hostapis: list[dict], preferred: str = "WASAPI") -> int | None`（名前に `preferred` を含む API、無ければ入力デバイスを最も多く持つ API）
  - `list_input_devices(all_devices: list[dict], hostapis: list[dict], preferred: str = "WASAPI") -> dict[str, int]`（表示名 → デバイス index。先頭は既定デバイス。同名は `" (2)"` を付与。`Microsoft Sound Mapper` は除外）
  - `stream_extra_settings(device_id: int, all_devices: list[dict], hostapis: list[dict])`（WASAPI デバイスなら `sd.WasapiSettings(auto_convert=True)`、それ以外 `None`）
  - `AudioService.start(device_id: int, extra_settings=None)`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_devices.py`:

```python
from snoreguard.devices import DEFAULT_DEVICE_LABEL, list_input_devices, select_hostapi

WIN_HOSTAPIS = [
    {"name": "MME", "devices": [0, 1, 2], "default_input_device": 1},
    {"name": "Windows DirectSound", "devices": [3, 4], "default_input_device": 3},
    {"name": "Windows WASAPI", "devices": [5, 6, 7], "default_input_device": 6},
    {"name": "Windows WDM-KS", "devices": [8], "default_input_device": 8},
]
WIN_DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2},
    {"name": "マイク (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 2},
    {"name": "スピーカー (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 0},
    {"name": "マイク (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2},
    {"name": "スピーカー", "hostapi": 1, "max_input_channels": 0},
    {"name": "スピーカー (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 0},
    {"name": "マイク (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 2},
    {"name": "Headset Microphone (Oculus Virtual Audio Device)", "hostapi": 2, "max_input_channels": 1},
    {"name": "Microphone (Realtek HD Audio Mic input)", "hostapi": 3, "max_input_channels": 2},
]
MAC_HOSTAPIS = [{"name": "Core Audio", "devices": [0, 1], "default_input_device": 0}]
MAC_DEVICES = [
    {"name": "MacBook Airのマイク", "hostapi": 0, "max_input_channels": 1},
    {"name": "MacBook Airのスピーカー", "hostapi": 0, "max_input_channels": 0},
]


def test_select_prefers_wasapi():
    assert select_hostapi(WIN_HOSTAPIS) == 2


def test_select_falls_back_to_api_with_inputs():
    assert select_hostapi(MAC_HOSTAPIS) == 0


def test_windows_list_has_no_duplicates_and_one_api():
    devices = list_input_devices(WIN_DEVICES, WIN_HOSTAPIS)
    assert list(devices) == [
        DEFAULT_DEVICE_LABEL,
        "マイク (Realtek(R) Audio)",
        "Headset Microphone (Oculus Virtual Audio Device)",
    ]
    assert devices[DEFAULT_DEVICE_LABEL] == 6
    assert devices["マイク (Realtek(R) Audio)"] == 6


def test_mac_list():
    devices = list_input_devices(MAC_DEVICES, MAC_HOSTAPIS)
    assert devices == {DEFAULT_DEVICE_LABEL: 0, "MacBook Airのマイク": 0}


def test_duplicate_names_get_suffix():
    hostapis = [{"name": "Windows WASAPI", "devices": [0, 1], "default_input_device": -1}]
    devices = [
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1},
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1},
    ]
    assert list_input_devices(devices, hostapis) == {"USB Mic": 0, "USB Mic (2)": 1}
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_devices.py -q`
Expected: ImportError

- [ ] **Step 3: 実装**

`src/snoreguard/devices.py`:

```python
"""入力デバイスの列挙。sounddevice の生データを受け取る純粋関数群。

PortAudio は同じ物理マイクを MME / DirectSound / WASAPI / WDM-KS ごとに
別デバイスとして列挙する。利用者に見せるのは 1 つのホスト API だけにする。
"""

import sounddevice as sd

DEFAULT_DEVICE_LABEL = "既定のデバイス"
_EXCLUDED_NAME_FRAGMENTS = ("Microsoft Sound Mapper",)


def select_hostapi(hostapis: list[dict], preferred: str = "WASAPI") -> int | None:
    """表示に使うホスト API の index。preferred を含む名前があればそれ、無ければ入力が最も多い API。"""
    for index, api in enumerate(hostapis):
        if preferred.lower() in str(api.get("name", "")).lower():
            return index
    best, best_count = None, -1
    for index, api in enumerate(hostapis):
        count = len(api.get("devices", []))
        if count > best_count:
            best, best_count = index, count
    return best


def list_input_devices(
    all_devices: list[dict], hostapis: list[dict], preferred: str = "WASAPI"
) -> dict[str, int]:
    """表示名 → デバイス index。先頭は既定デバイス。"""
    api_index = select_hostapi(hostapis, preferred)
    if api_index is None:
        return {}
    api = hostapis[api_index]
    result: dict[str, int] = {}

    default_index = api.get("default_input_device", -1)
    if isinstance(default_index, int) and 0 <= default_index < len(all_devices):
        if all_devices[default_index].get("max_input_channels", 0) > 0:
            result[DEFAULT_DEVICE_LABEL] = default_index

    for index in api.get("devices", []):
        if not (0 <= index < len(all_devices)):
            continue
        info = all_devices[index]
        if info.get("max_input_channels", 0) <= 0:
            continue
        name = str(info.get("name", f"Unknown Device {index}"))
        if any(fragment in name for fragment in _EXCLUDED_NAME_FRAGMENTS):
            continue
        label, n = name, 2
        while label in result:
            label = f"{name} ({n})"
            n += 1
        result[label] = index
    return result


def stream_extra_settings(device_id: int, all_devices: list[dict], hostapis: list[dict]):
    """WASAPI 共有モードで 16kHz を開くための設定。WASAPI 以外は None。"""
    if not (0 <= device_id < len(all_devices)):
        return None
    api_index = all_devices[device_id].get("hostapi")
    if api_index is None or not (0 <= api_index < len(hostapis)):
        return None
    if "wasapi" in str(hostapis[api_index].get("name", "")).lower():
        return sd.WasapiSettings(auto_convert=True)
    return None
```

`audio_service.py`: `start(self, device_id: int, extra_settings=None)` にし `self._extra_settings = extra_settings` を保持、`sd.InputStream(...)` に `extra_settings=self._extra_settings` を渡す。テストのフェイクストリームは `**kwargs` を受けるので影響なし。

`app.py`:
- import に `from snoreguard import devices`。
- `_populate_mic_list` と `_get_input_devices`, `_add_default_device`, `_get_default_device_id`, `_is_valid_default_device`, `_should_add_device`, `_add_individual_devices`, `_should_skip_device`, `_is_preferred_api` を削除し、次に置き換える:

```python
    def _populate_mic_list(self):
        """入力デバイス一覧を取得してコンボボックスに反映"""
        try:
            all_devices = list(sd.query_devices())
            hostapis = list(sd.query_hostapis())
            self.input_devices = devices.list_input_devices(all_devices, hostapis)
            self._all_devices, self._hostapis = all_devices, hostapis
            if not self.input_devices:
                self.add_log("入力デバイスが見つかりません。", "warning")
            self._update_mic_combobox()
        except Exception as e:  # noqa: BLE001
            self._handle_mic_list_error(e)

    def refresh_devices(self):
        """PortAudio を再初期化してデバイス一覧を取り直す（検出停止中のみ）"""
        if self.is_running or self.is_initializing:
            self.add_log("検出停止中にデバイス一覧を更新してください", "warning")
            return
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:  # noqa: BLE001
            self.add_log(f"オーディオの再初期化に失敗: {e}", "error")
        self._populate_mic_list()
        self.add_log("デバイス一覧を更新しました", "system")
```

`_update_mic_combobox` の保存デバイス不在時のフォールバック後に `self.add_log(f"前回のマイク『{saved_device}』が見つかりません。{self.mic_var.get()} を選択しました", "warning")` を出す（`saved_device` が truthy で一覧に無い場合）。`_start_detection_async` → `_initialize_audio_system` 内の `self.audio_service.start(device_id)` を `self.audio_service.start(device_id, devices.stream_extra_settings(device_id, self._all_devices, self._hostapis))` に。テスト用の事前ストリーム（`test_stream = sd.InputStream(...)`）にも同じ `extra_settings` を渡す。

`ui.py` `_create_control_card`: コンボボックスの行を `combo_frame`（grid 2 列）にし、右に `ctk.CTkButton(combo_frame, text="更新", width=50, command=app.refresh_devices, font=self.font_s)` を置く。

- [ ] **Step 4: テスト・スモーク・コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.ui; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/devices.py tests/test_devices.py
git commit -m "feat: 入力デバイス列挙を純粋関数に切り出し、ホスト API を 1 つに固定"
git add src/snoreguard/app.py src/snoreguard/ui.py src/snoreguard/audio_service.py
git commit -m "feat: マイク一覧の「更新」ボタンと WASAPI の自動変換設定を追加"
```

---

### Task 25: librosa を numpy/scipy 実装に置き換える

**Files:**
- Create: `src/core/features.py`
- Test: `tests/test_features_equivalence.py`（librosa がある間だけ実行）, `tests/test_features.py`
- Modify: `src/core/rule_processor.py`（`FeatureExtractor`, `_warmup_librosa`）
- Modify: `src/core/settings.py`（`f0_confidence_threshold` 既定値/範囲、`settings_version=3` と移行）
- Modify: `src/main.py`（`prepare_app_data` の文言）、`pyproject.toml`（librosa 削除、filterwarnings 削除）
- Modify: `tests/test_app_settings.py`（version 3）, `tests/test_rule_processor_errors.py`（pyin モンキーパッチ → `core.features.yin`）

**Interfaces:**
- Produces（`core.features`）:
  - `frame_signal(y, frame_length, hop_length) -> np.ndarray`（形状 `(n_frames, frame_length)`、`n_frames = 1 + len(y) // hop_length`）
  - `rms(frames) -> np.ndarray`, `zero_crossing_rate(frames) -> np.ndarray`, `spectral_centroid(frames, sr) -> np.ndarray`
  - `yin(frames, sr, fmin, fmax, trough_threshold=0.1, voiced_confidence_min=0.2) -> tuple[np.ndarray, np.ndarray]`（`f0`（無声は 0）, `confidence = 1 - CMNDF最小値`）
  - `FeatureExtractor.extract_features` の戻り値キーは不変（`rms, spectral_centroid, zcr, f0, voiced_probs`）。`voiced_probs` の意味が「pyin の有声確率」から「YIN の周期性信頼度」に変わる。
  - `RuleSettings.f0_confidence_threshold` 既定値 `0.5`、`SLIDER_RANGES["f0_confidence_threshold"] = (0.1, 0.95, 0.01)`。`AppSettings.settings_version = 3`。version < 3 の JSON を読むときは `rule_settings.f0_confidence_threshold` を既定値に戻す。

- [ ] **Step 1: 等価性テストと機能テストを書く**

`tests/test_features_equivalence.py`:

```python
import numpy as np
import pytest

from core import features

librosa = pytest.importorskip("librosa")

SR, FRAME, HOP = 16000, 800, 200


@pytest.fixture
def audio():
    rng = np.random.default_rng(42)
    t = np.arange(SR) / SR
    return (0.2 * np.sin(2 * np.pi * 120 * t) + 0.05 * rng.normal(size=SR)).astype(np.float32)


def test_frame_count_matches(audio):
    frames = features.frame_signal(audio, FRAME, HOP)
    assert frames.shape == (1 + len(audio) // HOP, FRAME)


def test_rms_matches_librosa(audio):
    ours = features.rms(features.frame_signal(audio, FRAME, HOP))
    ref = librosa.feature.rms(y=audio, frame_length=FRAME, hop_length=HOP)[0]
    np.testing.assert_allclose(ours, ref, rtol=1e-3, atol=1e-5)


def test_zcr_matches_librosa(audio):
    ours = features.zero_crossing_rate(features.frame_signal(audio, FRAME, HOP))
    ref = librosa.feature.zero_crossing_rate(y=audio, frame_length=FRAME, hop_length=HOP)[0]
    np.testing.assert_allclose(ours, ref, atol=3e-3)


def test_centroid_matches_librosa(audio):
    ours = features.spectral_centroid(features.frame_signal(audio, FRAME, HOP), SR)
    ref = librosa.feature.spectral_centroid(y=audio, sr=SR, n_fft=FRAME, hop_length=HOP)[0]
    np.testing.assert_allclose(ours[2:-2], ref[2:-2], rtol=2e-2)
```

`tests/test_features.py`:

```python
import numpy as np

from core import features

SR, FRAME, HOP = 16000, 800, 200


def _tone(freq, sec=1.0, amp=0.3):
    t = np.arange(int(SR * sec)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_yin_tracks_low_tone():
    f0, conf = features.yin(features.frame_signal(_tone(100), FRAME, HOP), SR, 50, 450)
    mid = slice(10, 70)
    assert abs(np.median(f0[mid]) - 100) < 2
    assert np.median(conf[mid]) > 0.8


def test_yin_tracks_high_tone():
    f0, conf = features.yin(features.frame_signal(_tone(440), FRAME, HOP), SR, 50, 450)
    assert abs(np.median(f0[10:70]) - 440) < 5


def test_yin_noise_has_low_confidence_and_unvoiced():
    noise = np.random.default_rng(1).normal(0, 0.1, SR).astype(np.float32)
    f0, conf = features.yin(features.frame_signal(noise, FRAME, HOP), SR, 50, 450)
    assert np.median(conf) < 0.5
    assert (f0 == 0).mean() > 0.5


def test_yin_silence_is_unvoiced():
    f0, conf = features.yin(np.zeros((5, FRAME), dtype=np.float32), SR, 50, 450)
    assert not f0.any()
    assert not conf.any()


def test_yin_runtime_is_fast_enough():
    import time

    frames = features.frame_signal(_tone(110), FRAME, HOP)
    t0 = time.perf_counter()
    for _ in range(5):
        features.yin(frames, SR, 50, 450)
    assert (time.perf_counter() - t0) / 5 < 0.2  # 1 秒分の音声を 200ms 以内に
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run --no-sync pytest tests/test_features_equivalence.py tests/test_features.py -q`
Expected: ImportError（`core.features` なし）

- [ ] **Step 3: `core/features.py` を実装**

```python
"""numpy/scipy だけで計算する音響特徴量。

librosa の rms / zero_crossing_rate / spectral_centroid / pyin を置き換える。
フレーム分割は librosa の center=True, pad_mode="constant" と同じ。
F0 は YIN（de Cheveigné & Kawahara 2002）の CMNDF で求め、信頼度は
1 - CMNDF の最小値（周期性の強さ）とする。
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import get_window


def frame_signal(y: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    """(n_frames, frame_length) のビュー。n_frames = 1 + len(y) // hop_length"""
    y = np.asarray(y, dtype=np.float32)
    pad = frame_length // 2
    padded = np.pad(y, (pad, pad), mode="constant")
    n_frames = 1 + (len(padded) - frame_length) // hop_length
    return sliding_window_view(padded, frame_length)[::hop_length][:n_frames]


def rms(frames: np.ndarray) -> np.ndarray:
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)).astype(np.float32)


def zero_crossing_rate(frames: np.ndarray) -> np.ndarray:
    """librosa 相当（pad=True: フレーム先頭を 1 回と数える）"""
    signs = np.signbit(frames)
    crossings = np.sum(signs[:, 1:] != signs[:, :-1], axis=1) + 1
    return (crossings / frames.shape[1]).astype(np.float32)


def spectral_centroid(frames: np.ndarray, sr: int) -> np.ndarray:
    n_fft = frames.shape[1]
    window = get_window("hann", n_fft, fftbins=True).astype(np.float32)
    magnitude = np.abs(np.fft.rfft(frames * window, axis=1))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    total = magnitude.sum(axis=1)
    centroid = (magnitude * freqs).sum(axis=1) / np.maximum(total, 1e-12)
    return centroid.astype(np.float32)


def yin(
    frames: np.ndarray,
    sr: int,
    fmin: float,
    fmax: float,
    trough_threshold: float = 0.1,
    voiced_confidence_min: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """フレームごとの (f0, confidence)。無声・無音は f0=0, confidence=0。"""
    n_frames, frame_length = frames.shape
    win = frame_length // 2
    tau_min = max(2, int(sr / fmax))
    tau_max = min(int(np.ceil(sr / fmin)), frame_length - win - 1)
    if tau_max <= tau_min:
        raise ValueError(f"fmin/fmax がフレーム長に対して不正です: {fmin}, {fmax}")

    x = frames.astype(np.float64)
    taus = np.arange(tau_max + 1)
    cumulative = np.cumsum(np.concatenate([np.zeros((n_frames, 1)), x**2], axis=1), axis=1)
    energy_tau = cumulative[:, taus + win] - cumulative[:, taus]  # sum x[tau:tau+win]^2
    energy_0 = energy_tau[:, :1]

    n_fft = 1 << int(np.ceil(np.log2(frame_length + win)))
    spectrum = np.fft.rfft(x, n_fft, axis=1)
    spectrum_win = np.fft.rfft(x[:, :win], n_fft, axis=1)
    correlation = np.fft.irfft(spectrum * np.conj(spectrum_win), n_fft, axis=1)[:, : tau_max + 1]

    difference = energy_0 + energy_tau - 2.0 * correlation
    difference[:, 0] = 0.0
    running = np.cumsum(difference[:, 1:], axis=1)
    cmndf = np.ones_like(difference)
    cmndf[:, 1:] = difference[:, 1:] * taus[1:] / np.maximum(running, 1e-12)

    f0 = np.zeros(n_frames, dtype=np.float32)
    confidence = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        if energy_0[i, 0] < 1e-10:
            continue  # 無音
        c = cmndf[i]
        best = None
        tau = tau_min
        while tau <= tau_max:
            if c[tau] < trough_threshold:
                while tau + 1 <= tau_max and c[tau + 1] < c[tau]:
                    tau += 1
                best = tau
                break
            tau += 1
        if best is None:
            best = tau_min + int(np.argmin(c[tau_min : tau_max + 1]))
        shift = 0.0
        if 1 <= best < tau_max:
            a, b, cc = c[best - 1], c[best], c[best + 1]
            denominator = a - 2 * b + cc
            if abs(denominator) > 1e-12:
                shift = float(np.clip(0.5 * (a - cc) / denominator, -1.0, 1.0))
        conf = float(np.clip(1.0 - c[best], 0.0, 1.0))
        confidence[i] = conf
        if conf >= voiced_confidence_min:
            f0[i] = sr / (best + shift)
    return f0, confidence
```

- [ ] **Step 4: テスト（等価性・機能）**

Run: `uv run --no-sync pytest tests/test_features_equivalence.py tests/test_features.py -q`
Expected: 全 PASS。許容誤差を超える場合は **実装を直す**（許容誤差を広げない）。

- [ ] **Step 5: `FeatureExtractor` を切り替える**

`rule_processor.py` の `import librosa` を削除し `from core import features` を追加。`extract_features` を:

```python
    def extract_features(self, audio_chunk: np.ndarray) -> Dict[str, np.ndarray]:
        """全特徴量を一括抽出。失敗時は FeatureExtractionError。"""
        try:
            frames = features.frame_signal(audio_chunk, self.frame_length, self.hop_length)
            f0, confidence = features.yin(frames, self.sample_rate, PYIN_FMIN_HZ, PYIN_FMAX_HZ)
            return {
                "rms": features.rms(frames),
                "spectral_centroid": features.spectral_centroid(frames, self.sample_rate),
                "zcr": features.zero_crossing_rate(frames),
                "f0": f0,
                "voiced_probs": confidence,
            }
        except Exception as e:
            raise FeatureExtractionError(str(e)) from e
```

`_warmup_librosa` を `_warmup` に改名（中身は同じ: ダミー音声で 1 回計算）。`core/constants.py` のコメントを「YIN の探索範囲」に直す。`tests/test_rule_processor_errors.py` の `monkeypatch.setattr(rp.librosa, "pyin", boom)` を `monkeypatch.setattr(rp.features, "yin", boom)` に（`boom` のシグネチャは `*args, **kwargs`）。

- [ ] **Step 6: 設定スキーマ version 3**

`core/settings.py`: `f0_confidence_threshold: float = 0.5`、`SLIDER_RANGES["f0_confidence_threshold"] = (0.1, 0.95, 0.01)`、`AppSettings.settings_version: int = 3`。`AppSettings.from_dict` で:

```python
        version = int(data.get("settings_version", 1) or 1)
        rule_data = dict(data.get("rule_settings") or {})
        if version < 3:
            # F0 信頼度の意味が pyin の有声確率から YIN の周期性信頼度に変わった
            rule_data.pop("f0_confidence_threshold", None)
```

を `rule_settings=RuleSettings.from_dict(rule_data)` の前に入れる。`tests/test_app_settings.py` の `settings_version == 2` を `== 3` に変え、テストを追加:

```python
def test_old_schema_resets_f0_confidence_threshold():
    s = AppSettings.from_dict(
        {"settings_version": 2, "rule_settings": {"f0_confidence_threshold": 0.05, "zcr_threshold": 0.1}}
    )
    assert s.rule_settings.f0_confidence_threshold == RuleSettings().f0_confidence_threshold
    assert s.rule_settings.zcr_threshold == 0.1
```

`tests/test_rule_settings.py::test_diff_lists_changed_fields_only` は変更不要（zcr のみ比較）。Phase 1 `test_f0_range.py` は `voiced_probs` を使っていないので不変。

- [ ] **Step 7: librosa を依存から外す**

`pyproject.toml` の dependencies から `"librosa>=0.9.2"` を削除し、`[tool.pytest.ini_options]` の `filterwarnings` 行を削除。`src/main.py` の `prepare_app_data` 内の文言を「音声エンジン準備中...」のままでよいがコメントから librosa/numba を外す。`src/snoreguard/auto_calibrator.py` に `librosa` の残存 import が無いことを `grep -rn librosa src` で確認（0 件であること）。

Run: `uv lock && uv sync --locked --all-groups && grep -c "name = \"librosa\"\|name = \"numba\"\|name = \"llvmlite\"\|name = \"scikit-learn\"\|name = \"soundfile\"\|name = \"soxr\"" uv.lock`
Expected: lock 更新成功、grep が `0`。

Run: `uv run --no-sync pytest -q`
Expected: 等価性テストは `skipped`（librosa 不在）、その他 PASS。

- [ ] **Step 8: コミット（3 つ）**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/core/features.py tests/test_features.py tests/test_features_equivalence.py
git commit -m "feat: numpy/scipy だけで RMS/ZCR/スペクトル重心/YIN を計算する core.features を追加"
git add src/core/rule_processor.py src/core/constants.py src/core/settings.py tests/test_rule_processor_errors.py tests/test_app_settings.py
git commit -m "refactor: 特徴量抽出を core.features に切り替え、F0 信頼度の既定値を設定スキーマ v3 で更新"
git add pyproject.toml uv.lock src/main.py
git commit -m "build: librosa/numba/scikit-learn 依存を削除"
```

---

### Task 26: onedir 配布・リリースワークフロー・第三者ライセンス一覧

**Files:**
- Modify: `SnoreGuard.spec`（onedir、excludes、datas）
- Create: `scripts/gen_third_party_licenses.py`, `.github/workflows/release.yml`
- Modify: `scripts/build.bat`, `README.md`, `.gitignore`（`THIRD_PARTY_LICENSES.md` は生成物）
- Test: `tests/test_third_party_licenses.py`

**Interfaces:**
- Produces: `scripts/gen_third_party_licenses.py` — `main(output: Path) -> int`（同梱パッケージの名前・バージョン・ライセンスを Markdown 表で書き出す）。`dist/SnoreGuard/SnoreGuard.exe` と `dist/SnoreGuard/THIRD_PARTY_LICENSES.md`。

- [ ] **Step 1: テスト**

`tests/test_third_party_licenses.py`:

```python
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "gen_third_party_licenses.py"
    spec = importlib.util.spec_from_file_location("gen_licenses", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generates_table_with_numpy(tmp_path):
    module = _load()
    out = tmp_path / "THIRD_PARTY_LICENSES.md"
    assert module.main(out) == 0
    text = out.read_text(encoding="utf-8")
    assert "| numpy |" in text
    assert "CPython" in text and "Tcl/Tk" in text and "PortAudio" in text
```

- [ ] **Step 2: 実装**

`scripts/gen_third_party_licenses.py`:

```python
#!/usr/bin/env python3
"""同梱する第三者パッケージのライセンス一覧を Markdown で生成する。"""

import sys
from importlib.metadata import distributions
from pathlib import Path

_EXTRA = [
    ("CPython", "https://www.python.org/", "PSF License"),
    ("Tcl/Tk", "https://www.tcl.tk/", "Tcl/Tk License (BSD-style)"),
    ("PortAudio", "http://www.portaudio.com/", "MIT-style (PortAudio License)"),
]


def _license_of(dist) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    if classifiers:
        return "; ".join(c.split("::")[-1].strip() for c in classifiers)
    raw = (meta.get("License") or "").strip()
    return raw.splitlines()[0][:80] if raw else "(不明)"


def main(output: Path) -> int:
    rows = []
    for dist in distributions():
        name = dist.metadata.get("Name")
        if not name or name.lower() in {"snoreguard-py", "pip", "setuptools", "wheel"}:
            continue
        rows.append((name, dist.version, _license_of(dist)))
    rows.sort(key=lambda r: r[0].lower())

    lines = [
        "# Third-party licenses",
        "",
        "SnoreGuard は MIT License で配布されます。同梱する以下のコンポーネントは、それぞれのライセンスに従います。",
        "",
        "| Package | Version | License |",
        "|---|---|---|",
    ]
    lines += [f"| {n} | {v} | {lic} |" for n, v, lic in rows]
    lines += ["", "## Runtime components", "", "| Component | URL | License |", "|---|---|---|"]
    lines += [f"| {n} | {u} | {lic} |" for n, u, lic in _EXTRA]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{output}: {len(rows)} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("THIRD_PARTY_LICENSES.md")))
```

`SnoreGuard.spec` を onedir に:

```python
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path(SPECPATH)

added_files = [
    (str(project_root / "src/assets/icon/icon.ico"), "assets/icon/"),
    (str(project_root / "src/assets/icon/icon.gif"), "assets/icon/"),
    (str(project_root / "pyproject.toml"), "."),
]
licenses = project_root / "THIRD_PARTY_LICENSES.md"
if licenses.exists():
    added_files.append((str(licenses), "."))

a = Analysis(
    [str(project_root / "src" / "main.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=added_files,
    hiddenimports=["customtkinter", "sounddevice", "pythonosc", "matplotlib.backends.backend_tkagg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["IPython", "tkinter.test", "matplotlib.tests", "numpy.tests", "scipy.tests", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SnoreGuard",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_root / "src/assets/icon/icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="SnoreGuard")
```

`scripts/build.bat` の `[2/3]` の前に `uv run --no-sync python scripts\gen_third_party_licenses.py` を追加し、最終行を `echo [3/3] 完了: dist\SnoreGuard\SnoreGuard.exe` に。`.gitignore` に `THIRD_PARTY_LICENSES.md` を追加。README の「インストール方法」は「ZIP を展開し、`SnoreGuard` フォルダ内の `SnoreGuard.exe` を実行」に整合させる。

`.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write
  id-token: write
  attestations: write

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv python install
      - name: Set version from tag
        shell: pwsh
        run: uv version ("${env:GITHUB_REF_NAME}".TrimStart("v"))
      - run: uv sync --locked --no-dev --group build
      - run: uv run --no-sync python scripts/gen_third_party_licenses.py
      - run: uv run --no-sync pyinstaller SnoreGuard.spec --clean
      - name: Package
        shell: pwsh
        run: |
          $name = "SnoreGuard-${env:GITHUB_REF_NAME}-win64.zip"
          Compress-Archive -Path dist/SnoreGuard -DestinationPath $name
          Get-FileHash $name -Algorithm SHA256 | Format-List | Out-File SHA256SUMS.txt -Encoding utf8
      - uses: actions/attest-build-provenance@v2
        with:
          subject-path: "SnoreGuard-*.zip"
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            SnoreGuard-*.zip
            SHA256SUMS.txt
          prerelease: ${{ contains(github.ref_name, '-') }}
          generate_release_notes: true
```

（`uv version` は `pyproject.toml` と `uv.lock` を更新するため、その後の `uv sync --locked` は整合する。タグが `v1.4.0-beta.4` なら version は `1.4.0-beta.4`。）

- [ ] **Step 3: テストとコミット**

Run: `uv run --no-sync pytest tests/test_third_party_licenses.py -q && uv run --no-sync ruff check .`

```bash
git add scripts/gen_third_party_licenses.py tests/test_third_party_licenses.py .gitignore
git commit -m "feat: 同梱パッケージの第三者ライセンス一覧を生成するスクリプトを追加"
git add SnoreGuard.spec scripts/build.bat README.md
git commit -m "build: 配布形式を onedir に変更し、ライセンス一覧を同梱"
git add .github/workflows/release.yml
git commit -m "ci: タグ push で Windows ビルド・SHA256・provenance 付きリリースを作成"
```

---

### Task 27: UI 負荷と運用面の磨き込み

**Files:**
- Modify: `src/snoreguard/app.py`（`UPDATE_INTERVAL_MS`, `_update_visuals`, `_draw_plots`, `_update_control_state`, `add_log`）
- Modify: `src/snoreguard/ui.py`（`_init_plots`, `_create_log_card`）
- Modify: `src/snoreguard/settings_manager.py`（`migrate_legacy_settings`）
- Test: `tests/test_settings_migration.py`, `tests/test_plot_decimation.py`

**Interfaces:**
- Produces:
  - `app.DISPLAY_POINTS = 800`, `app.UPDATE_INTERVAL_MS = 100`, `app.MAX_LOG_LINES = 2000`, `app.LOG_COLORS: dict[str, str]`
  - `snoreguard.plotting.decimate_envelope(samples: np.ndarray, points: int) -> tuple[np.ndarray, np.ndarray]`（**新規** `src/snoreguard/plotting.py`、(min, max) 各 `points` 要素）、`plotting.mask_to_blocks(mask_frames: np.ndarray, hop_length: int, n_samples: int, points: int) -> np.ndarray`（bool、`points` 要素）
  - `settings_manager.migrate_legacy_settings(target: Path, candidates: list[Path]) -> Path | None`

- [ ] **Step 1: テスト**

`tests/test_plot_decimation.py`:

```python
import numpy as np

from snoreguard.plotting import decimate_envelope, mask_to_blocks


def test_envelope_shape_and_values():
    x = np.linspace(-1, 1, 16000, dtype=np.float32)
    lo, hi = decimate_envelope(x, 800)
    assert lo.shape == hi.shape == (800,)
    assert np.all(lo <= hi)
    assert lo[0] == -1 and abs(hi[-1] - 1) < 1e-6


def test_mask_blocks_cover_frames():
    mask = np.zeros(81, dtype=bool)
    mask[40:45] = True  # フレーム 40-44 → サンプル 8000-9000
    blocks = mask_to_blocks(mask, 200, 16000, 800)
    assert blocks.shape == (800,)
    assert blocks[400:450].all()
    assert not blocks[:390].any() and not blocks[460:].any()
```

`tests/test_settings_migration.py`:

```python
import json

from snoreguard.settings_manager import migrate_legacy_settings


def test_copies_first_existing_candidate(tmp_path):
    target = tmp_path / "new" / "settings.json"
    old = tmp_path / "snore_guard_settings.json"
    old.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert migrate_legacy_settings(target, [tmp_path / "missing.json", old]) == old
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_noop_when_target_exists(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{}", encoding="utf-8")
    old = tmp_path / "old.json"
    old.write_text('{"a": 1}', encoding="utf-8")
    assert migrate_legacy_settings(target, [old]) is None
    assert target.read_text(encoding="utf-8") == "{}"
```

- [ ] **Step 2: 実装**

`src/snoreguard/plotting.py`:

```python
"""波形表示用のデシメーション。16000 点を毎フレーム描くのは重いので包絡線にする。"""

import numpy as np


def decimate_envelope(samples: np.ndarray, points: int) -> tuple[np.ndarray, np.ndarray]:
    block = max(1, len(samples) // points)
    usable = samples[: block * points].reshape(points, block)
    return usable.min(axis=1), usable.max(axis=1)


def mask_to_blocks(mask_frames: np.ndarray, hop_length: int, n_samples: int, points: int) -> np.ndarray:
    per_sample = np.repeat(np.asarray(mask_frames, dtype=bool), hop_length)[:n_samples]
    if len(per_sample) < n_samples:
        per_sample = np.pad(per_sample, (0, n_samples - len(per_sample)))
    block = max(1, n_samples // points)
    return per_sample[: block * points].reshape(points, block).any(axis=1)
```

`ui.py` `_init_plots`: `app.waveform_x` を `np.linspace(0, sr, app.DISPLAY_POINTS)` に、`waveform_line` はそのまま（`np.zeros(app.DISPLAY_POINTS)` で初期化）、`waveform_fill` も同じ x で初期化。`_create_log_card` の末尾に:

```python
        for level, color in app.LOG_COLORS.items():
            app.log_text.tag_config(level, foreground=color)
```

`app.py`:
- クラス定数 `DISPLAY_POINTS = 800`, `MAX_LOG_LINES = 2000`, `LOG_COLORS = {"error": "#E74C3C", "warning": "#F39C12", "detection": "#2ECC71", "success": "#2ECC71", "vrchat": "#7289DA", "osc": "#7289DA", "scheduler": "#9B59B6"}`。`UPDATE_INTERVAL_MS = 100`。
- `_draw_plots` を:

```python
    def _draw_plots(self):
        """包絡線（min/max）で波形を描き、検出候補区間をオレンジで重ねる"""
        lo, hi = decimate_envelope(self.display_buffer, self.DISPLAY_POINTS)
        self.waveform_line.set_ydata((lo + hi) / 2)
        self.waveform_fill.remove()
        highlight = mask_to_blocks(
            self.display_mask, HOP_LENGTH, len(self.display_buffer), self.DISPLAY_POINTS
        )
        self.waveform_fill = self.ax_waveform.fill_between(
            self.waveform_x, lo, hi, where=highlight, color="orange", alpha=0.6, interpolate=False
        )
        self.plot_canvas.draw_idle()
```

（`from core.constants import HOP_LENGTH`, `from snoreguard.plotting import decimate_envelope, mask_to_blocks`。波形自体も包絡線の塗りで見せたい場合は `fill_between(x, lo, hi, color="cornflowerblue", alpha=0.5)` をもう 1 つ保持して同様に更新する。）
- `_update_visuals` の `if updated: self._draw_plots()` を `if updated and self.root.state() != "iconic": self._draw_plots()` に。
- `_update_control_state`: スライダーは常に `state="normal"`（`for _, _, scale in ...: scale.configure(state="normal")`）。検出中の変更は共有オブジェクト経由で即反映される。
- `add_log`: `self.log_text.insert(tk.END, log_line, level)` とし、挿入後に

```python
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > self.MAX_LOG_LINES:
                self.log_text.delete("1.0", f"{line_count - self.MAX_LOG_LINES + 1}.0")
```

`settings_manager.py` に追加:

```python
def migrate_legacy_settings(target: Path, candidates: list[Path]) -> Path | None:
    """旧バージョンの設定ファイル（exe と同じフォルダ等）を新しい場所へ一度だけコピーする"""
    if target.exists():
        return None
    for old in candidates:
        try:
            if old.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, target)
                logger.info(f"旧設定ファイルを移行しました: {old} -> {target}")
                return old
        except OSError as e:
            logger.warning(f"旧設定ファイルの移行に失敗: {old}: {e}")
    return None
```

（`import shutil`。）`app.py` の `__init__`、`SettingsManager(...)` 生成の直前に:

```python
        migrated = migrate_legacy_settings(
            Path(SETTINGS_FILE),
            [Path.cwd() / "snore_guard_settings.json", Path(sys.executable).parent / "snore_guard_settings.json"],
        )
```

（`import sys`、`from snoreguard.settings_manager import SettingsManager, migrate_legacy_settings`。`migrated` が truthy なら `self.root.after(1500, lambda: self.add_log(f"旧設定ファイルを移行しました: {migrated}", "system"))`。）

- [ ] **Step 3: テスト・スモーク・コミット**

Run: `uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.ui; print('import ok')"`

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add src/snoreguard/plotting.py tests/test_plot_decimation.py src/snoreguard/app.py src/snoreguard/ui.py
git commit -m "perf: 波形を包絡線にデシメートし 10fps 化、最小化中は描画をスキップ、検出区間の強調を修正"
git add src/snoreguard/settings_manager.py tests/test_settings_migration.py
git add -p src/snoreguard/app.py
git commit -m "feat: 旧バージョンの設定ファイルを新しい保存先へ移行"
git add src/snoreguard/app.py src/snoreguard/ui.py
git commit -m "feat: 検出ログの行数上限と level ごとの色分け、検出中もスライダーを操作可能に"
```

（`git add -p` で分けられない場合はまとめてよい。）

---

### Task 28: `app.py` の整理（デッドコード・未使用引数・型ヒント）

**Files:**
- Modify: `src/snoreguard/app.py`, `src/snoreguard/ui.py`

- [ ] **Step 1: 削除と整理**

- `self.HAS_OSC` と `if self.HAS_OSC:` 分岐をすべて削除（常に有効）。
- `_save_app_settings(self, send_feedback=True, skip_osc_feedback=False, *args)` → `_save_app_settings(self, send_feedback: bool = True)`。`ui.py` の `command=lambda: app._save_app_settings(skip_osc_feedback=True)` を `command=lambda: app._save_app_settings(send_feedback=False)` に。
- `_update_control_state_initializing` を削除し、呼び出しを `_update_control_state()` に。
- `periodicity_timer_start_time` 等のうち未使用のものを `grep -n` で確認して削除。
- 公開メソッド（`toggle_detection`, `apply_rule_settings`, `reset_settings`, `refresh_devices`, `handle_osc_*`, `handle_avatar_change`, `run_on_ui_thread`, `add_log`, `update_time_scheduler_settings`, `open_calibration_modal`）に戻り値型 `-> None` と引数型を付ける。
- モジュール先頭に docstring（「ダッシュボードのコントローラ。スレッド境界は `run_on_ui_thread` / `event_queue` のみ」）を追加。

- [ ] **Step 2: テスト・スモーク・コミット**

Run: `uv run --no-sync ruff check . && uv run --no-sync ruff format . && uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import snoreguard.app, snoreguard.ui; print('import ok')"`

```bash
git add src/snoreguard/app.py src/snoreguard/ui.py
git commit -m "refactor: app.py のデッドコード（HAS_OSC・未使用引数・重複メソッド）を削除し型ヒントを整備"
```

---

### Task 29: Phase 3 の仕上げと最終確認

- [ ] **Step 1: 全体確認**

Run: `uv lock --check && uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync pytest -q && uv run --no-sync python -c "import sys; sys.path.insert(0,'src'); import main, snoreguard.app, snoreguard.ui, snoreguard.calibration_modal; print('import ok')"`

- [ ] **Step 2: 起動時間と依存の確認**

Run: `uv run --no-sync python -c "import time; t=time.perf_counter(); import sys; sys.path.insert(0,'src'); from core.rule_processor import RuleBasedProcessor; from core.settings import RuleSettings; RuleBasedProcessor(RuleSettings(), lambda: None); print(f'engine init {time.perf_counter()-t:.2f}s')"`
Expected: 1 秒未満（numba JIT が無い）。

- [ ] **Step 3: GUI スモーク（可能なら）**

ダッシュボード表示、検出開始→波形が包絡線で描かれる→「更新」ボタン→停止→終了。

- [ ] **Step 4: コミット**

```bash
git add docs/superpowers/plans/2026-08-23-windows-refresh-phase3.md
git commit -m "docs: Phase 3 実装計画の進捗を更新"
```
