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

### 最終ブランチレビューと修正ウェーブ（2026-08-29）

タスク単位のレビューをすべて通過した後、`8af3d93..2fcd10c` に対してブランチ全体のレビューを実施した。
結果は **Ready to merge = No**、Critical 1 件・Important 6 件。タスク単位のレビューでは検出できなかった
統合上の欠陥である。

**Critical（修正済み）:** librosa の `center=True` により 1 秒チャンクが個別に反射パディングされ、
チャンク両端のスペクトル重心が閾値(500Hz)を超えて `final_mask` が必ず端で False になっていた。
その結果 Task 10 で実装したチャンク跨ぎのセグメント引き継ぎが**実音声では一度も発動せず**、
`max_duration_seconds` による連続音の棄却が機能していなかった（監査 P0 #04 が未解決のまま）。
Task 10 のテストはマスクを直接 `SegmentProcessor` に投入していたため、この欠陥を検出できなかった
（**計画側の欠陥**: 再現手順そのものを受け入れ条件にすべきだった）。

修正: フレーム分割をチャンク間で連続させた（600 サンプルのテールを繰り越し、4 つの librosa 呼び出しを
すべて `center=False` に、フレーム→時刻の対応を `-(FRAME_LENGTH-HOP_LENGTH)/SAMPLE_RATE` で補正）。
実測での検証（再レビュアーが独立に再現）:

| 指標 | 修正前 | 修正後 |
|---|---|---|
| 連続ハム音 30 秒の検出回数 | 4 回（元の main は 7 回） | **0 回** |
| 1 秒チャンクあたりのフレーム数 | 81 | 80 |
| チャンク境界を跨ぐ 1.0 秒のいびき | 2 イベント（0.463s + 0.488s） | **1 イベント（0.9875s, ts 0.500s）** |
| `_open_frames` の境界跨ぎ継続 | 常に 0（分岐が死んでいた） | 77→2397 と継続 |
| 静音チャンクの処理時間 | 111 ms | **1.0 ms** |

**併せて修正した Important:** pyin をエネルギー閾値未満のチャンクでスキップ（読み取りスレッドのブロック解消）／
`add_log` をファイルログにミラーし level を反映（Phase 1 の新診断が全てログに残るように）／
検出開始時に VRChat のミュート状態未取得を警告／F0最小値スライダーの下限を 50Hz に拡張し説明書に明記／
無音ウォッチドッグを UI タイマー駆動にしてワーカー停止も検知。

**再レビュー結果:** 全項目 ADDRESSED（実行検証済み）、**Ready to merge = Yes**。
残った Low 3 件のうち「`_check_silence` の例外で描画ループが恒久停止し得る」のみマージ前に修正（`eecec07`）、
他 2 件は Phase 2 Task 15 / Task 17 の計画本文に追記して持ち越した。

**最終状態:** 90 テスト green、ruff クリーン、`uv lock --check` OK、import／GUI 起動スモーク成功。

**次のステップ:** `docs/superpowers/plans/2026-08-23-windows-refresh-phase2.md` を Task 13 から実行する。
