from __future__ import annotations

import time
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
        move_timeout_seconds: int = 300,
    ) -> None:
        self.save_path = save_path
        self.category = category
        self.move_timeout_seconds = move_timeout_seconds
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
        if not _add_succeeded(result):
            raise RuntimeError(f"qBittorrent rejected the download: {result}")

    def completed(
        self,
        categories: tuple[str, ...] | None = None,
    ) -> list[TorrentDownload]:
        self.client.auth_log_in()
        downloads: dict[str, TorrentDownload] = {}
        for category in categories or (self.category,):
            torrents = self.client.torrents_info(
                status_filter="completed",
                category=category,
            )
            for torrent in torrents:
                download = _to_download(torrent)
                downloads[download.torrent_hash] = download
        return list(downloads.values())

    def accept(
        self,
        torrent_hash: str,
        verified_path: str,
        verified_category: str,
    ) -> TorrentDownload:
        self.client.auth_log_in()
        self._ensure_category(verified_category, verified_path)
        self.client.torrents_set_location(
            location=verified_path,
            torrent_hashes=torrent_hash,
        )
        promoted = self._wait_for_location(torrent_hash, verified_path)
        self.client.torrents_set_category(
            category=verified_category,
            torrent_hashes=torrent_hash,
        )
        return promoted

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

    def _wait_for_location(
        self,
        torrent_hash: str,
        verified_path: str,
    ) -> TorrentDownload:
        deadline = time.monotonic() + self.move_timeout_seconds
        while True:
            torrents = self.client.torrents_info(torrent_hashes=torrent_hash)
            if not torrents:
                raise RuntimeError(
                    f"qBittorrent no longer reports torrent {torrent_hash}"
                )
            torrent = torrents[0]
            save_path = Path(str(_torrent_value(torrent, "save_path")))
            state = str(_torrent_value(torrent, "state")).casefold()
            if save_path == Path(verified_path) and state != "moving":
                return _to_download(torrent)
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out moving torrent {torrent_hash} to {verified_path}"
                )
            time.sleep(0.5)


def _torrent_value(torrent: Any, key: str) -> Any:
    if isinstance(torrent, dict):
        return torrent.get(key, "")
    return getattr(torrent, key, "")


def _to_download(torrent: Any) -> TorrentDownload:
    return TorrentDownload(
        torrent_hash=str(_torrent_value(torrent, "hash")),
        name=str(_torrent_value(torrent, "name")),
        content_path=Path(str(_torrent_value(torrent, "content_path"))),
    )


def _add_succeeded(result: Any) -> bool:
    if isinstance(result, str):
        return result.strip().lower() in {"ok.", "ok"}
    if hasattr(result, "get"):
        success_count = int(result.get("success_count", 0) or 0)
        pending_count = int(result.get("pending_count", 0) or 0)
        return success_count + pending_count > 0
    return False
