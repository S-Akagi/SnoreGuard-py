import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SettingsManager:
    """
    アプリケーション設定の永続化と管理を担当
    - JSON形式の設定ファイルの読み書き
    - キャッシュ機能
    - ファイルの変更検知
    - スレッドセーフな操作
    """

    def __init__(self, filepath: Path):
        logger.debug(f"SettingsManager初期化: {filepath}")
        self.filepath = filepath
        self._cache: dict[str, Any] | None = None  # キャッシュ
        self._cache_lock = threading.RLock()  # ロック
        self._file_mtime: float | None = None  # ファイルの変更時刻
        self.last_error: str | None = None  # 直近の読込で退避したときのメッセージ
        self.backup_path: Path | None = None  # 退避先
        logger.debug("SettingsManager初期化完了")

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
            self.last_error = f"設定ファイルが壊れていたため初期化しました（退避先: {backup.name}）: {error}"
        except OSError as move_error:
            self.last_error = (
                f"設定ファイルを読み込めません（退避も失敗）: {error} / {move_error}"
            )
        logger.error(self.last_error)

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
            self._cache = None
            self._file_mtime = None
