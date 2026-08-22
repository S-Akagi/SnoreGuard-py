# SnoreGuard Windows 版改修 — 監査仕様書（2026-08-23）

監査の全文（151 件の指摘、根拠コード、反証コメント）は Artifact「SnoreGuard 改修監査」を参照。本書は実装計画が参照する要約。
対象コード: ブランチ `feature/windows-refresh`（main + Dependabot 5 件 + `releace/v1.4.x` v1.4.0-beta.3 をマージ済み）。

## 全体制約

- Python 3.11 以上（`tomllib` 使用）。依存管理は uv（`pyproject.toml` + `uv.lock`）。
- 対象 OS は Windows 10/11。開発・CI では macOS/Linux でも `import` とテストが通ること（`winsound` は隔離する）。
- Git のコミットには Claude を示す Author / Co-Authored-By / 生成注記を一切入れない。コミットは小さく、`type: 日本語要約` 形式（feat/fix/refactor/test/build/ci/docs/style）。
- 検出エンジンの定数: SAMPLE_RATE=16000, FRAME_LENGTH=800, HOP_LENGTH=200, 帯域通過 80–1600Hz, 分析チャンク 1.0 秒。
- VRChat OSC: 送信 127.0.0.1:9000、受信 127.0.0.1:9001。ミュート操作は `/input/Voice` 1→0（Toggle モード前提）。
- 設定ファイル: `%APPDATA%\SnoreGuard\snore_guard_settings.json`。ログ: `%LOCALAPPDATA%\SnoreGuard\logs\snoreguard.log`。
- UI の文言・コメントは日本語。ruff check / ruff format を CI で強制。

## 最優先課題（根本原因ごとに統合、優先順）

### 01. [P0] 設定オブジェクトの参照ズレ — リセット／自動調整の結果が検出器に届かない

- 工数: S
- 関連指摘: conc-03, det-03, qual-01, rob-04

**何が起きているか**: `app.py:770`（リセット）と `app.py:1121-1122`（キャリブレーション適用）は `self.rule_settings` を**新しいオブジェクトに差し替える**が、`RuleBasedProcessor` 配下の4クラス（`rule_processor.py:258, 276-282`）は初期化時に受け取ったオブジェクトを保持し続ける。CTkSlider は変数更新では `command` を発火しないので UI 経由の書き戻しも起きない。

**影響**: 「キャリブレーション結果を適用しました」と表示されても検出は旧閾値のまま。以降スライダーを動かしても一切反映されず、再起動すると JSON から読み直して直る——再現困難な不具合として報告される。

**対処**: オブジェクトを差し替えず**フィールドをコピー**する（`for f in fields(RuleSettings): setattr(self.rule_settings, f.name, getattr(new, f.name))`）か、`AudioService.update_settings(new)` を用意して processor 配下の参照を一括更新する。音声スレッドとの整合は「次チャンクから適用」のスナップショット方式が安全。

### 02. [P0] 検出スレッドが静かに死に、UI は朝まで「検出中」のまま

- 工数: M
- 関連指摘: rob-03, win-06, conc-06, det-05, qual-05, crit-04, robust-v-02

**何が起きているか**: `audio_service.py:140-149` は例外をログ1行で握り、`AudioService.is_running=False` にするだけ。`app.is_running`（`app.py:292`）は True のままで、App へ通知するコールバックが存在しない。死因は複数ある：VR ヘッドセットの再接続／スリープ復帰によるストリーム例外、librosa 失敗時のフォールバック配列が **20フレーム**なのに本番は **81フレーム**で `ValueError`（`rule_processor.py:112-117` vs `149-152`）、F0 スライダーの範囲重なり（`ui.py:506-507`）で `f0_min ≥ f0_max` にすると pyin が `ParameterError`（F0最小値を上限150まで上げるだけで発生）、設定 JSON の型不正。

**影響**: 就寝中に検出が止まっても画面は「検出中」・停止ボタン有効のまま。いびきをかいてもミュートされず、ユーザーは朝まで気付けない。venv で `f0_min_hz=150/f0_max_hz=100` による停止を再現済み。

**対処**: (1) `AudioService` に `on_stream_stopped(error)` コールバックを追加し、App 側で待機状態へ戻す＋通知＋同名デバイスの自動再開。(2) フォールバック配列を廃止し、そのチャンクをスキップ。(3) `_on_rule_setting_change` でペアのスライダーを相互クランプし、`RuleSettings.validate()` を JSON 読込・適用・開始時に呼ぶ。(4) RMS が 60 秒ゼロなら無音警告を出すウォッチドッグ。

### 03. [P0] ミュート状態が不明なときの「探りトグル」が、逆にマイクを開く

- 工数: M
- 関連指摘: rob-02, win-07, crit-09, win-v-01

**何が起きているか**: `app.py:529-540`：`is_vrchat_muted is None` なら `/input/Voice` をトグルして反応を待つ。3秒後の `_cancel_mute_sync_timeout`（`app.py:896-904`）は待機フラグを下ろすだけで状態は None のまま → 次の検出で再トグル。`MuteSelf` が届かない条件は現実的で、受信ポート **9001 固定バインド**（`handler.py:46-48`）の失敗（VRCFaceTracking 等との競合）はログのみで続行する（`handler.py:57-60`）。正常系でも「既にミュート中」の利用者に対しては探りで数百ms マイクが開く。多重起動防止も無く、2インスタンスが打ち消し合う。

**影響**: 検出のたびにミュート／解除が交互に発生し、いびきの半分がフレンドに聞こえ続ける。本アプリの中核価値の反転。

**対処**: (1) 状態不明時はトグルを送らない（探りは明示オプトイン）。(2) 9001 バインド失敗を赤で明示し、受信ポートを設定可能に。(3) mDNS で既に取得している OSCQuery の HTTP ポート（SRV）を捨てず、`GET /avatar/parameters/MuteSelf` で実値を読む。(4) 起動直後に `CreateMutexW("Local\\SnoreGuard")` で単一起動を保証。

### 04. [P0] 検出ロジック：1秒チャンク分割で最大持続時間が無効、周期性判定が間隔を見ない

- 工数: M
- 関連指摘: det-01, det-04, det-06, logic-v-02

**何が起きているか**: `audio_service.py:22,172` は 1 秒ごとに `process_audio_chunk` を呼び、`SegmentProcessor`（`rule_processor.py:202-237`）はチャンク内でしかセグメントを切らない。1チャンク最大 81 フレーム＝1.0125 秒なので `max_duration_seconds`（既定 3.0、スライダー下限 0.5）は**構造的に発火しない**。`_check_periodicity`（`349-368`）は窓内件数しか見ず、UI にスライダーがある `min/max_event_interval_seconds` は**どこからも参照されない**。イベントの timestamp は `datetime.now()` なので同一チャンク内の4バーストは同時刻。帯域通過は `zi` 無しで毎チャンク先頭 40ms に過渡が出る。

**影響**: PC ファンの低周波うなり・換気扇のハムなど 4 秒以上続く低い連続音で約 4 秒ごとに「いびき」判定（venv で 100Hz 倍音連続音 8 秒→2 回発火を再現）。逆に 1 回のいびきが境界で 2 イベントに分断され早期誤検出。

**対処**: `SegmentProcessor` に「継続中セグメント」を持たせてチャンクを跨いで持ち越し、False に転じた時点で min/max を判定。timestamp はサンプルクロック（チャンク開始＋`start_frame*hop/sr`）で付与。隣接イベント間隔を `min/max_event_interval_seconds` で検証（実装するか UI から外す）。`sosfilt_zi` で状態を持ち越す。

### 05. [P0] windowed exe ではログも例外も消える——「起動しない」しか報告できない

- 工数: S
- 関連指摘: rob-05, win-02, qual-06, crit-03, conc-18, rob-06

**何が起きているか**: `main.py:8` の `basicConfig` は stderr 宛だが、`SnoreGuard.spec` の `console=False` では `sys.stderr` が None → 全ログ・print・Tk コールバック例外が消える。さらに `main.py:136-152` の包括 `except` が PyInstaller の「Unhandled exception」ダイアログ（最後の砦）も無効化。`threading.excepthook` / `report_callback_exception` も未設定。設定 JSON の `UnicodeDecodeError`（Shift_JIS で保存した場合）も未捕捉で無言終了（`settings_manager.py:54`）。

**影響**: 起動失敗・ワーカースレッド例外・OSC ハンドラ例外がすべて不可視。サポート不能。

**対処**: `%LOCALAPPDATA%\SnoreGuard\logs\` に `RotatingFileHandler`（1MB×3）、`sys.stderr` が None なら StreamHandler を付けない。最上位 except で `messagebox.showerror("起動に失敗しました。ログ: …")`。`threading.excepthook` と `root.report_callback_exception` をファイルへ。UI に「ログフォルダを開く」。設定読込は `except (OSError, ValueError)` ＋ `isinstance(dict)` 検証＋壊れたファイルを `.bak` へ退避して通知。

### 06. [P1] 「リセット」が不完全——スケジューラは旧時刻で動き続ける

- 工数: S
- 関連指摘: conc-11, rob-11, qual-10

**何が起きているか**: `app.py:762-784` は `app_settings` を既定値に差し替え、チェックボックス変数を False にするが `time_scheduler.stop()/configure()` を呼ばない。CTkCheckBox は変数更新で `command` を発火しないため、スレッドは `enabled=True`・旧時刻のまま。`notification_var`/`auto_mute_var`/`mic_var` も戻らず、次の保存で UI 値が既定値を上書き。確認ダイアログも無い。

**影響**: リセット後、UI は「無効」なのに 22:00 に検出が突然始まる。README の「すべての設定を初期値に戻せます」が成り立たない。

**対処**: `AppSettings` dataclass を導入し、`apply_settings(s)` を唯一の入口に（audio_service.update_settings → time_scheduler.apply → UI 反映）。リセットは `apply_settings(AppSettings())` ＋ `askyesno`。

### 07. [P1] タイムスケジューラは「HH:MM 一致」のエッジ検出のみ——無人運転に耐えない

- 工数: M
- 関連指摘: win-05, rob-26, crit-10, qual-v02, conc-05, robust-v-03

**何が起きているか**: `time_scheduler.py:106-165` は毎秒 `%H:%M` 文字列が一致した分だけ発火。時間帯の途中で起動しても開始されず、スリープで該当分を跨げばその夜は何も起きない。失敗時は `messagebox`（対話 UI）を出すだけで再試行しない（`app.py:198-204, 305-314`）。`_start_detection` に `is_running` ガードが無く、手動開始中に開始時刻が来ると再初期化され `_update_visuals` ループが二重化する。

**影響**: 23:10 に起動して「22:00〜06:00 で自動」と信じて寝ると検出されない。USB マイクの認識遅れで 1 回失敗すると朝まで無防備。

**対処**: 「現在時刻が [start, end) 内か」を**レベル**で評価（日跨ぎ対応）し、前回状態との差分で callback。起動時・設定変更時・毎ループで評価。非対話経路（scheduler/osc）ではダイアログを出さず 60 秒間隔で再試行。`_start_detection`/`_stop_detection` に状態ガード、`_handle_initialization_error` では必ず `audio_service.stop()`。

### 08. [P1] 「VRChat 接続中」は UDP クライアントを作っただけで緑になる

- 工数: M
- 関連指摘: rob-01, crit-08, qual-12

**何が起きているか**: `osc_query_service.py:134-141` は `SimpleUDPClient` 生成だけで `status_callback(True)`。UDP なので VRChat の起動有無は一切確認されず、`app.py:873` の「VRChat 未接続」は実質到達不能。さらにステータスラベルが検出状態と多重化され（`app.py:860-875`）、一度検出を開始すると接続表示は二度と更新されない。`OSCQueryService` は名前に反して OSCQuery（HTTP/mDNS 広告）を実装していない。

**影響**: VRChat 未起動でも緑表示で安心して就寝。MANUAL のトラブルシューティング手順（「未接続」表示を確認）が最初から成立しない。

**対処**: 接続状態は実測で導出：9001 で直近 N 秒以内に `/avatar/parameters/*` を受信したか、または OSCQuery HTTP `?HOST_INFO` の応答。接続インジケータを検出状態ラベルから分離し、検出中も表示。クラス名・コメントを実装に合わせる。

### 09. [P1] 自動キャリブレーションの統計設計が成立していない

- 工数: M
- 関連指摘: cal-01, cal-02, cal-03, rob-09, rob-10, qual-02, qual-v01, robust-v-01, conc-08, conc-10, logic-v-04, logic-v-03, conc-v01

**何が起きているか**: ラベルごとに AudioSample が 1 つしかないため `np.std`=0、p25=p75=mean となり分離品質は常に 1.0（`auto_calibrator.py:334-346, 433-436`）。F0信頼度閾値を「いびき」と「会話」の中点に置くため、会話の有声確率が高い通常ケースでいびき自身が閾値を下回る（`386-389`、venv 再現）。特徴量パラメータが実行時と異なる（frame 480/hop 240, pyin 50–400Hz vs 800/200, f0_min–max）。無音録音で閾値 0 が生成され、信頼度に関係なく適用できる。「停止」がステージ進行を止めない（`calibration_modal.py:311`）。解析（10–20 秒分の pyin）が Tk メインスレッドで走り各ステージ後に UI が数秒固まる。

**影響**: 「完了！信頼度 9x%」と表示されるが、適用後に本人のいびきが検出されなくなる／閾値 0 で検出不能になる。№1 の参照ズレにより症状は再起動後に出るため原因追跡が困難。

**対処**: 検出器と同じ `FeatureExtractor`（同一 sr/frame/hop/pyin 範囲/帯域通過）を共用。フレームレベル分布（既に計算している `*_p25/p75/std`）で統計。閾値は方向付きで決め、いびき側の分位点を必ず含むようクランプ。RMS 下限・信頼度 0.5 未満は適用ボタンを出さない。録音→解析→次ステージをキャンセル可能な状態機械にし、解析はワーカースレッドで。

### 10. [P1] スレッド境界の規律——停止のたびに 1 秒フリーズ、終了時にプロセス残留

- 工数: M
- 関連指摘: conc-01, rob-07, conc-04, qual-04, rob-19, conc-07, cal-04, conc-09, rob-30, conc-12, conc-16, conc-17, rob-20, win-16, conc-13, conc-v02, conc-15, qual-v03

**何が起きているか**: `AudioService.stop()`（`audio_service.py:103-108`）はメインスレッドで `join(1.0)`、ワーカーは `finally` で `log_callback → root.after`（`146-148`）。tkinter の他スレッド呼び出しはメインスレッドがイベントを処理するまでブロックするため**必ず 1 秒タイムアウト**。OSC 受信ハンドラ（python-osc の ThreadingMixIn、データグラム毎スレッド）は `_start_detection`/`_stop_detection`/設定保存を**直接**実行（`handler.py:98-121`）。ハンドラスレッドは非デーモンで、終了処理中に `root.after` 待ちに入ると `mainloop` 終了後に永久待機→ `SnoreGuard.exe` が残留し 9001 を保持。PortAudio のリアルタイムコールバックからも Tk を呼んでいる（`auto_calibrator.py:73-75`）。

**影響**: 停止ボタン・×で 1〜2.5 秒固まる。ウィンドウは消えたのにプロセスが残り、次回起動で 9001 が使用中 → №3 の盲目トグルへ連鎖。

**対処**: ワーカー→UI は `queue` のみ（既存 `data_queue` と同じ経路にログ/状態通知を載せる）、メインスレッドで `join` しない（`after(100, poll)` で `is_alive` 監視）。OSC ハンドラは値を受け取って `safe_after` で委譲するだけにし、状態判定はメインスレッドで。`ThreadingOSCUDPServer` のサブクラスで `daemon_threads=True`、`stop()` で `server_close()`。`winsound.Beep` は別スレッド／`SND_ASYNC` にしミュート送信を先に。

### 11. [P1] pyin を 70–150Hz の狭帯域で実行——F0 範囲ルールが恒真、高い声が折り返す

- 工数: M
- 関連指摘: det-02

**何が起きているか**: `rule_processor.py:81-88` は `fmin=f0_min_hz, fmax=f0_max_hz` で pyin を呼ぶ。出力は必ず [fmin, fmax] 内に量子化されるので `f0_range_mask`（`154-160`）は有声フラグと同値。YIN は真の周期の整数倍にも谷を持つため、範囲外のピッチはサブハーモニクスとして高信頼度で出る（venv：純音 440Hz → 146.6Hz voiced=1.00、220Hz 基音の話し声 → 109.8Hz）。

**影響**: F0 最小/最大スライダーとキャリブレーションの F0 範囲が実質無効。UI の F0 表示も 200Hz の声を 100Hz と出し、調整を誤らせる。

**対処**: pyin は広帯域（`fmin=50, fmax=450`、frame 800 なら警告なし）で実行し、得られた f0 に `f0_min/max_hz` を後段フィルタとして適用。

### 12. [P1] VRChat からのパラメータ再送を「利用者の操作」として受理し、設定まで書き換える

- 工数: M
- 関連指摘: crit-01

**何が起きているか**: `handler.py:89-121` → `app.py:1214-1242`：受信値が現状と異なれば無条件に開始/停止・チェックボックス変更・JSON 保存。VRChat はアバターのロード／変更時に全パラメータの現在値（未保存なら既定値）を再送するが、SnoreGuard 側は VRChat 起動を検知して自状態を再プッシュする仕組みを持たない。

**影響**: 22:00 にスケジューラで開始 → 22:30 に VRChat 起動・アバターロード → `ToggleDetection=False` が届き就寝中の検出が停止。UI で OFF にした自動ミュートがアバター既定値で ON に戻り保存される。

**対処**: 直前に自分が送った値と一致する受信は無視（エッジのみ操作扱い）。`/avatar/change` を購読し、受信後 1〜2 秒は入力を無視して `_send_status_feedback()` で SnoreGuard 側を真のソースに。OSC 経由の変更はセッション内一時上書きに留める（永続化は設定で選択）。

### 13. [P1] mDNS：LAN からの偽装応答で送信先を乗っ取られ、細工パケット 1 個で無限ループ

- 工数: S
- 関連指摘: sec-01, sec-02, rob-21, conc-14, win-19

**何が起きているか**: `mdns_client.py:84` は `0.0.0.0:5353` で待受け、応答の送信元 IP をそのまま `handler.py:191-196` で OSC 送信先に採用（検証なし、名前が違えば何度でも上書き）。`_parse_name`（`221-233`）は圧縮ポインタのジャンプ上限・訪問済み検出が無く、自己参照ポインタで受信スレッドが 100% CPU の無限ループ（venv 再現）。なお VRChat の OSCQuery 広告には TXT `osc-port` が存在しないため、この発見経路は**実質デッドコード**で、有用な SRV（HTTP ポート）は捨てられている。

**影響**: 同一 LAN の隣接者による自動ミュート無効化／DoS（影響は LAN 内・機能妨害に限定＝medium）。GIL により GUI・音声スレッドのスケジューリングにも干渉。

**対処**: ループバック以外の送信元は採用しない（既定 127.0.0.1:9000 優先、候補提示に留める）。ジャンプ上限（16）＋前方ポインタのみ＋訪問済み集合で違反時はパケット破棄。SRV ポートを OSCQuery HTTP 問い合わせに使うか、mDNS 機能自体を削除して単純化。

### 14. [P1] HiDPI：スプラッシュの tk.Tk() が先に HWND を作り、DPI 認識設定が無効化される

- 工数: S
- 関連指摘: crit-02, win-04, rob-29, crit-05

**何が起きているか**: CustomTkinter は `CTk()` 生成時に `SetProcessDpiAwareness(2)` を呼ぶが、その前に `quick_splash.py:15` の `tk.Tk()` が表示されている。Microsoft の仕様上、HWND 生成後の DPI モード変更はサポートされず（戻り値未検査で黙殺）、プロセスは DPI 非対応のまま。さらに `main.py:64-68`（1000×700 中央）と `ui.py:106`（1280×720）の二重 geometry で、150% では画面外にはみ出す。結果モーダルは 500×800 固定で 768px 画面では「適用」ボタンが押せない。

**影響**: 125% 以上の環境で文字・プロットがぼやけ、CTk の自動スケーリングも効かない。開発者は同じ経路で起動するため気付かない。

**対処**: `main.py` 冒頭（どの Tk ウィンドウも作る前）で `ctypes.windll.shcore.SetProcessDpiAwareness(2)`、またはスプラッシュも `ctk.CTk()` に。より堅牢には spec の `EXE(manifest=…)` に `PerMonitorV2` を宣言。geometry は UIBuilder に一本化し、画面サイズでクランプ。モーダルはスクロール可能に。

### 15. [P2] 依存・ビルド・CI・ライセンスの整備

- 工数: M→L
- 関連指摘: qual-07, dep-01, dep-02, dep-07, win-08, rob-23, win-10, dep-06, win-20, dep-08, win-09, sec-v-02, dep-09, sec-v-01, dep-10, win-12, rob-25, dep-11, dep-03, dep-04, dep-05, dep-12, dep-13, dep-14, deps-v-02, win-11, deps-v-03, win-17, win-21, win-13, qual-14, qual-11, qual-13

**何が起きているか**: `tomllib`（3.11+）を使いながら `requires-python>=3.10`／CI 3.10／README 3.10。`pyinstaller` が実行時依存、`packaging` は未宣言（推移依存頼み）。`requirements.txt` は初回コミット以来未更新。README のビルド手順は spec と異なり `pyproject.toml` を同梱しないので version 0.0.0 の exe ができる。CI は未固定 `pip install ruff` のみで Windows ジョブも lock 検証も無し。リリースはローカル `uv run`（`--locked` 無し）・未署名・チェックサム無し・`upx=True`。librosa は 4 関数のために numba/llvmlite/scikit-learn/soundfile/soxr（展開後 ~150MB、LGPL 成分含む）を同梱しているが第三者ライセンス表示が無い。テストは皆無。

**影響**: 協力者が README 通り 3.10 で環境構築すると即落ち。Dependabot PR が exe を壊しても CI は緑。配布物の再現性・真正性を誰も検証できない。

**対処**: **S**：`requires-python>=3.11`、`packaging` 追加、`pyinstaller` を `[dependency-groups] build` へ、`requirements.txt` 削除（または `uv export` 生成物と明記）、README を `uv sync → scripts\build.bat` に一本化、`upx=False`。**M**：CI を uv 化（`uv lock --check`、ruff、pytest、windows-latest で import スモーク＋pyinstaller ビルド、pip-audit）、タグ push で Windows ビルド＋SHA256＋provenance を付ける `release.yml`、`pip-licenses` で THIRD_PARTY_LICENSES.md 生成。**L**：librosa を numpy/scipy 実装（RMS/ZCR/重心は数行、F0 は YIN 約 60 行）に置換し依存・起動時間・ライセンス義務を同時に解消。

### 16. [P2] UI・運用の磨き込み（長時間の就寝運用を前提に）

- 工数: S〜L
- 関連指摘: rob-13, rob-12, ui-01, rob-14, rob-15, win-v-04, rob-16, rob-17, rob-18, rob-22, rob-27, rob-28, crit-06, rob-31, rob-24, rob-32, crit-07, win-03, win-v-02, conc-19, det-07, win-15, win-14, qual-v04, crit-11, qual-03, qual-08, qual-09

**何が起きているか**: 50ms ごとに 16000 点の Line2D を Agg で全再描画（実測 ≈34ms/回、最小化中も継続）。波形のオレンジ強調はフレームマスク 81 要素を先頭 81 サンプルに当てており実質非表示。検出中はスライダーが無効で MANUAL の「ランプを見ながら調整」が不可能。マイク一覧に MME/DirectSound/WDM-KS の重複、再列挙ボタン無し。検出ログは無上限で level が無視される。**ミュート解除の経路が存在せず**（停止・終了・スケジューラ終了後もミュートのまま）、VRChat が Push-to-Talk だと機能しないことも未記載。v1.3.0 で設定パスを変えたが移行処理が無い。`app.py` は 1285 行の god object で UIBuilder がウィジェットを `setattr` 注入、VRC 層が private メソッドを直接呼ぶ。

**影響**: 一晩で単コアの過半を消費（VR のフレーム落ち・発熱）。調整ワークフローが成立しない。起床後フレンドに声が届かない。機能追加のたびに 3 ファイルを同時修正し、回帰をテストで検出できない。

**対処**: min/max エンベロープで 800 点程度にデシメート＋10fps＋最小化時スキップ。マスクを `np.repeat(mask, hop)` で展開。検出中もスライダー有効。ホスト API を 1 つに固定（WASAPI + `auto_convert=True`）し「更新」ボタン追加。ログ上限＋level で色分け。「検出停止時にミュートを解除」オプション（自分がミュートした場合のみ）＋ MANUAL に Toggle モード必須を明記。旧パスからの一回限り移行＋`settings_version`。段階的に `app.py` を分割（提案構成は qual-03 参照）。

## ロードマップ

### Step 0: 今すぐ（このブランチで）

- `origin/releace/v1.4.x`（v1.4.0-beta.2/3、4 コミット）をマージ — **衝突なしを確認済み**。beta.3 は「自動調整でダッシュボード選択デバイスを使う」修正を含む（本監査の rob-08 等はこれで解消）。
- pyproject の整合（3.11 統一・packaging 追加・pyinstaller を build グループへ）、README のビルド手順を一本化、`upx=False`。
- ファイルログ＋excepthook＋起動失敗ダイアログ（№5）。以降の全修正の検証基盤になる。
- 単一起動ミューテックス（№3 の一部）。

### Phase 1: 1〜2 週：就寝中のミュートを確実にする

- №1 参照ズレの修正（S）→ `AudioService.update_settings()`。
- №2 ストリーム死亡の伝播・フォールバック廃止・スライダー相互クランプ・`RuleSettings.validate()`。
- №3 状態不明時の盲目トグル禁止、9001 バインド失敗の明示。
- №4 チャンク跨ぎセグメント・サンプルクロック timestamp・間隔検証・`sosfilt_zi`。
- pytest 基盤：`core`（マスク/セグメント/周期性）、`StatisticalCalibrator`、`SettingsManager`、mDNS パーサ、スケジューラ判定の 5 本。CI を uv 化して Windows スモークを追加。

### Phase 2: 2〜4 週：無人運転と UI の信頼性

- №6 リセット／`AppSettings` 導入、№7 スケジューラのレベル評価＋再試行、№8 接続状態の実測表示。
- №9 キャリブレーションの `FeatureExtractor` 共用・統計修正・品質ゲート・キャンセル。
- №10 スレッド境界の規約化（queue 経由のみ、OSC ハンドラは委譲のみ、daemon_threads）。
- №11 pyin 広帯域化、№12 OSC 再送の扱い、№13 mDNS 硬化（または削除）、№14 DPI。
- ミュート解除オプションと MANUAL 追記（Toggle モード必須、自動解除しない旨）。

### Phase 3: 継続：構造と配布

- `app.py` の段階的分割（Phase0〜5 の移行手順は qual-03）。ruff ルール拡張（I/UP/B/ARG/BLE/G/T20）。
- librosa を numpy/scipy 実装に置換（判定一致率テストを先に用意）。onedir 配布化。
- `release.yml`（タグ push → Windows ビルド → SHA256 → provenance）、コード署名（SignPath Foundation 等）、THIRD_PARTY_LICENSES。
- 50ms 再描画の軽量化、マイク一覧の API 固定、設定移行。

## うまくできている点（壊さないこと）

- OSC 受信は `127.0.0.1:9001` のループバック限定、アップデータは TLS 検証＋timeout 付きでブラウザを開くだけ（自動 DL/実行なし）。
- 設定保存は一時ファイル＋`replace` の原子的書き込み、`ensure_ascii=False`。危険なデシリアライズ（pickle/eval）は無い。
- `uv.lock`（sha256 付き）をコミットし `.python-version` で固定。Dependabot のセキュリティ PR を取り込んでいる。
- 音声→UI のデータ受け渡しに `queue.Queue`、ワーカー→UI 通知を `ThreadSafeHandler.safe_after` に集約しようとする設計意図。
- 検出エンジンの骨格（16kHz、frame 800/hop 200 で全特徴量が 81 フレームに揃う、1 秒チャンクを欠落なく連結、1 チャンク ≈23ms）は妥当で、既定閾値の単位も計算される量と整合している。
- `core`（検出ロジック）が UI に依存せず、`SettingsManager`・mDNS パーサ・`StatisticalCalibrator`・スケジューラ判定は今日そのまま単体テストを書ける。
- 日本語コメント・docstring が全体に行き渡り、モジュールごとに `logging.getLogger(__name__)` を統一。
