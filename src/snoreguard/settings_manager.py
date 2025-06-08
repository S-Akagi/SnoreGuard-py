import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# 設定ファイルの読み書きを管理するクラス
class SettingsManager:
    def __init__(self, filepath: Path):
        logger.debug(f"SettingsManager初期化: {filepath}")
        self.filepath = filepath
        self._cache: dict[str, Any] | None = None  # キャッシュ
        self._cache_lock = threading.RLock()  # ロック
        self._file_mtime: float | None = None  # ファイルの変更時刻
        logger.debug("SettingsManager初期化完了")

    # 設定をファイルから読み込む
    def load(self, default_settings: dict[str, Any]) -> dict[str, Any]:
        logger.debug(f"設定読み込み開始: {self.filepath}")
        with self._cache_lock:
            # ファイルの変更時刻をチェック
            if self.filepath.exists():
                current_mtime = self.filepath.stat().st_mtime  # ファイルの変更時刻

                # キャッシュが有効で、ファイルが変更されていない場合
                if (
                    self._cache is not None  # キャッシュが有効
                    and self._file_mtime is not None  # ファイルの変更時刻が有効
                    and current_mtime == self._file_mtime  # ファイルの変更時刻が一致
                ):
                    logger.debug("キャッシュから設定を返却")
                    return self._cache.copy()

                # ファイルを読み込んでキャッシュを更新
                try:
                    with open(self.filepath, encoding="utf-8") as f:
                        settings = json.load(f)  # 設定を読み込む

                    self._cache = settings  # キャッシュを更新
                    self._file_mtime = current_mtime  # ファイルの変更時刻を更新
                    logger.info(f"設定ファイル読み込み完了: {len(settings)}個の設定")
                    return settings.copy()  # 設定を返却

                except (OSError, json.JSONDecodeError) as e:
                    logger.error(f"設定ファイル読み込みエラー: {e}")
                    print(f"設定ファイルの読み込みに失敗しました: {e}")

            # ファイルが存在しないか読み込み失敗時はデフォルトを返す
            logger.debug("デフォルト設定を使用")
            self._cache = default_settings.copy()  # デフォルト設定をキャッシュにコピー
            self._file_mtime = None  # ファイルの変更時刻をクリア
            return default_settings.copy()  # デフォルト設定を返却

    # 設定をファイルに保存
    def save(self, settings: dict[str, Any]):
        logger.debug(f"設定保存開始: {self.filepath}")
        with self._cache_lock:
            try:
                # 一時ファイルを作成
                temp_filepath = self.filepath.with_suffix(".tmp")

                with open(temp_filepath, "w", encoding="utf-8") as f:
                    json.dump(
                        settings,
                        f,
                        ensure_ascii=False,
                        indent=2,
                        separators=(",", ": "),
                    )

                # 一時ファイルをファイルに置き換え
                temp_filepath.replace(self.filepath)

                # キャッシュを更新する
                self._cache = settings.copy()
                if self.filepath.exists():
                    self._file_mtime = self.filepath.stat().st_mtime
                logger.info(f"設定保存完了: {len(settings)}個の設定")

            except OSError as e:
                logger.error(f"設定保存エラー: {e}")
                print(f"設定の保存に失敗しました: {e}")
                # 一時ファイルが残っている場合はクリーンアップ
                temp_filepath = self.filepath.with_suffix(".tmp")
                if temp_filepath.exists():
                    try:
                        temp_filepath.unlink()
                        logger.debug("一時ファイルをクリーンアップ")
                    except OSError:
                        logger.warning("一時ファイルクリーンアップ失敗")
                        pass

    # キャッシュをクリア
    def clear_cache(self):
        logger.debug("設定キャッシュクリア")
        with self._cache_lock:
            self._cache = None  # キャッシュをクリア
            self._file_mtime = None  # ファイルの変更時刻をクリア
