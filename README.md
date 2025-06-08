# SnoreGuard - VRChat連携いびき検出アプリ

<p align="center">
  <img src="src/assets/icon/icon.ico" alt="SnoreGuard Screenshot" width="100"/>
</p>

<p align="center">
  <strong>あなたの快適なVR睡眠をサポートします。</strong>
</p>

<p align="center">
  <a href="https://github.com/S-Akagi/SnoreGuard-py/releases">
    <img src="https://img.shields.io/badge/version-v1.0.0-blue?logo=github" alt="GitHub release">
  </a>
  <a href="https://github.com/S-Akagi/SnoreGuard-py/blob/main/LICENSE">
    <img src="http://img.shields.io/badge/license-MIT-blue.svg?style=flat" alt="License">
  </a>
  <a href="https://github.com/S-Akagi/SnoreGuard-py/actions/workflows/CI.yml">
    <img src="https://github.com/S-Akagi/SnoreGuard-py/actions/workflows/CI.yml/badge.svg" alt="CI Status">
  </a>
</p>

**SnoreGuard**は、マイク入力からリアルタイムでいびきを検出し、VRChat内で自動でミュートするWindows向けデスクトップアプリケーションです。

## 主な機能

* **高精度ないびき検出**: 音声の音響特徴に基づいたルールベースのエンジンで、リアルタイムにいびきを検出します。
* **VRChat自動ミュート連携**: いびきを検出すると、OSC経由でVRChatのマイクを自動的にミュートします。
* **リアルタイム分析表示**: 入力音声の波形やスペクトラム、分析状況をリアルタイムで視覚的に確認できます。
* **詳細な検出ログ**: いついびきが検出されたか、VRChatへの通知状況などをログで確認できます。
* **柔軟な感度設定**: UI上のスライダーを操作して、いびき検出の感度を直感的に調整できます。

## 分析プロセスについて

SnoreGuardは、以下のステップでいびきを分析・検出しています。

1. **音声フィルタリング**: マイクから入力された音声のうち、いびきの特徴が現れやすい周波数帯（80Hz〜1600Hz）を重点的に取り出し、関係のないノイズを低減します。 
2. **特徴量抽出**: 音声から「音の大きさ(エネルギー)」「音の高さ(F0)」「音色の明るさ(スペクトル重心)」「音の複雑さ(ゼロ交差率)」など、複数の音響的な特徴をリアルタイムで計算します。
3. **いびきらしさの判定**: 計算された特徴量が、いびき特有のパターン（例：エネルギーが大きく、比較的低い音で、倍音構造がはっきりしている）と一致するかをフレーム単位で判定します。
4. **持続時間の検証**: 「いびきらしい」と判断された状態が、短すぎるノイズや長すぎる環境音ではない、適切な長さで続いているかを確認します。
5. **周期性の検証**: いびき特有の呼吸リズムを捉えるため、候補となるイベントが一定時間内に一定回数以上、周期的に発生しているかを最終チェックします。
6. **最終検知**: すべての条件を満たした場合にのみ「いびき」と断定し、VRChatへミュート通知を送信します。 

## 動作環境

* **OS**: Windows 10 / 11
* **その他**: VRChatがOSC（Open Sound Control）を受信できる状態で実行されていること。

## インストール方法

1.  [GitHubリリースページ](https://github.com/S-Akagi/SnoreGuard-py/releases)にアクセスします。
2.  最新バージョンの`SnoreGuard.zip`のような名前のファイルをダウンロードします。
3.  ダウンロードしたZIPファイルを任意の場所に展開（解凍）します。
4.  展開したフォルダの中にある`SnoreGuard.exe`を実行すると、SnoreGuardが起動します。

## 使い方

1.  **マイクの選択**: アプリケーションを起動したら、「コントロール」セクションのドロップダウンメニューから、使用したいマイクを選択します。
2.  **検出開始**: 「検出開始」ボタンをクリックすると、いびきの検出が始まります。
3.  **VRChat連携**: 「VRChat自動ミュート」のチェックボックスがオンになっていることを確認してください。VRChatが起動していれば、いびき検出時に自動でミュートされます。
4.  **感度調整**: 「ルール設定」セクションのスライダーを調整することで、検出の感度を変更できます。

より詳しい使い方は、[説明書](./docs/MANUAL.md)をご覧ください。

## 注意事項

* 本アプリケーションは医療機器ではありません。睡眠時無呼吸症候群などの診断・治療目的での使用は絶対におやめください。
* VRChatの利用規約を遵守してご使用ください。
* 本アプリケーションの使用によって生じたいかなる損害についても、開発者は責任を負いません。詳細は[利用規約](./docs/TERMS_OF_USE.md)をご確認ください。

## 開発者向け情報

### ビルド方法

1.  Python 3.10環境を準備します。
2.  リポジトリをクローンします。
3.  依存ライブラリをインストールします。
    ```bash
    pip install -r requirements.txt
    ```
4.  アプリケーションを実行します。
    ```bash
    python src/main.py
    ```
5.  実行ファイルをビルドする場合 (PyInstallerを使用):
    ```bash
    pyinstaller --noconfirm --onefile --windowed --add-data "src/assets;assets" --icon "src/assets/icon/icon.ico" "src/main.py"
    ```

## ライセンス

このプロジェクトは[MITライセンス](https://github.com/S-Akagi/SnoreGuard-py/blob/main/LICENSE)のもとで公開されています。

---
