import logging
import sys
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)


def get_project_version() -> str:
    """
    pyproject.tomlからプロジェクトのバージョンを取得します
    """
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            project_root = Path(sys._MEIPASS)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent

        toml_path = project_root / "pyproject.toml"

        if not toml_path.is_file():
            logger.error(f"pyproject.tomlが見つかりません: {toml_path}")
            return "0.0.0"

        with open(toml_path, "rb") as f:
            toml_dict = tomllib.load(f)

        version = toml_dict.get("project", {}).get("version")
        if not version:
            logger.error("[project]テーブルにversionが見つかりません")
            return "0.0.0"

        return version

    except Exception as e:
        logger.error(f"バージョンの取得に失敗しました: {e}", exc_info=True)
        return "0.0.0"


__version__ = get_project_version()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Project Version: {__version__}")
