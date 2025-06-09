import logging
import webbrowser

import requests
from packaging.version import parse as parse_version

logger = logging.getLogger(__name__)

# アップデートを確認するGitHubリポジトリ
GITHUB_REPO = "S-Akagi/SnoreGuard-py"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

# Boothページ
BOOTH_URL = "https://s-akagi0610.booth.pm/items/7024946"


class Updater:
    """
    アプリケーションのアップデートを確認
    """

    def __init__(self, current_version: str):
        self.current_version = parse_version(current_version)
        self.latest_version_info = None
        logger.debug(f"Updater初期化完了. 現在のバージョン: {self.current_version}")

    def check_for_updates(self) -> dict | None:
        """
        GitHubリポジトリの最新リリースを確認し、アップデートが必要か判断
        """
        logger.info("アップデートの確認を開始...")
        try:
            response = requests.get(GITHUB_API_URL, timeout=10)
            response.raise_for_status()
            self.latest_version_info = response.json()
            logger.debug("GitHub APIから最新リリース情報を取得しました。")

            latest_version_str = self.latest_version_info.get(
                "tag_name", "v0.0.0"
            ).lstrip("v")
            latest_version = parse_version(latest_version_str)

            logger.info(
                f"現在のバージョン: {self.current_version}, 最新バージョン: {latest_version}"
            )

            # 現在のバージョンより新しいバージョンがあるかを確認
            if latest_version > self.current_version:
                logger.info(f"新しいバージョン {latest_version} が利用可能です。")
                return {
                    "latest_version": str(latest_version),
                    "release_notes": self.latest_version_info.get(
                        "body", "リリースノートはありません。"
                    ),
                    "release_url": self.latest_version_info.get(
                        "html_url", GITHUB_RELEASES_URL
                    ),
                }
            else:
                logger.info("アプリケーションは最新です。")
                return None

        except requests.RequestException as e:
            logger.error(
                f"アップデートチェック中にネットワークエラーが発生しました: {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"アップデートチェック中に予期せぬエラーが発生しました: {e}",
                exc_info=True,
            )
            return None

    def open_release_page(self):
        """
        最新リリースのWebページをブラウザで開きます。
        """
        if self.latest_version_info:
            url = self.latest_version_info.get("html_url", GITHUB_RELEASES_URL)
            logger.info(f"リリースベージを開きます: {url}")
            webbrowser.open(url)
        else:
            logger.warning("最新リリース情報がないため、ページを開けません。")

    def open_booth_page(self):
        """
        Boothページをブラウザで開きます。
        """
        logger.info(f"Boothページを開きます: {BOOTH_URL}")
        webbrowser.open(BOOTH_URL)
