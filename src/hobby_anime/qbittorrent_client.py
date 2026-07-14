from __future__ import annotations

from pathlib import Path
from typing import Any

import qbittorrentapi

from hobby_anime.models import TorrentDownload


class QBittorrentGateway:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        save_path: str,
        category: str,
        client: Any | None = None,
    ) -> None:
        self.save_path = save_path
        self.category = category
        self.client = client or qbittorrentapi.Client(
            host=host,
            port=port,
            username=username,
            password=password,
        )

    def connect(self) -> str:
        self.client.auth_log_in()
        return str(self.client.app.web_api_version)

    def add(self, download_url: str) -> None:
        self.client.auth_log_in()
        self._ensure_category(self.category, self.save_path)

        result = self.client.torrents_add(
            urls=download_url,
            save_path=self.save_path,
            category=self.category or None,
        )
        if str(result).strip().lower() not in {"ok.", "ok"}:
            raise RuntimeError(f"qBittorrent rejected the download: {result}")

    def completed(self) -> list[TorrentDownload]:
        self.client.auth_log_in()
        torrents = self.client.torrents_info(
            status_filter="completed",
            category=self.category,
        )
        return [
            TorrentDownload(
                torrent_hash=str(_torrent_value(torrent, "hash")),
                name=str(_torrent_value(torrent, "name")),
                content_path=Path(str(_torrent_value(torrent, "content_path"))),
            )
            for torrent in torrents
        ]

    def accept(
        self,
        torrent_hash: str,
        verified_path: str,
        verified_category: str,
    ) -> None:
        self.client.auth_log_in()
        self._ensure_category(verified_category, verified_path)
        self.client.torrents_set_location(
            location=verified_path,
            torrent_hashes=torrent_hash,
        )
        self.client.torrents_set_category(
            category=verified_category,
            torrent_hashes=torrent_hash,
        )

    def reject(self, torrent_hash: str, rejected_category: str) -> None:
        self.client.auth_log_in()
        self._ensure_category(rejected_category, self.save_path)
        self.client.torrents_stop(torrent_hashes=torrent_hash)
        self.client.torrents_set_category(
            category=rejected_category,
            torrent_hashes=torrent_hash,
        )

    def _ensure_category(self, category: str, save_path: str) -> None:
        if not category:
            return
        categories = self.client.torrents_categories()
        if category not in categories:
            self.client.torrents_create_category(
                name=category,
                save_path=save_path,
            )


def _torrent_value(torrent: Any, key: str) -> Any:
    if isinstance(torrent, dict):
        return torrent.get(key, "")
    return getattr(torrent, key, "")
