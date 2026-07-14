from __future__ import annotations

from typing import Any

import qbittorrentapi


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
        categories = self.client.torrents_categories()
        if self.category and self.category not in categories:
            self.client.torrents_create_category(
                category=self.category,
                save_path=self.save_path,
            )

        result = self.client.torrents_add(
            urls=download_url,
            save_path=self.save_path,
            category=self.category or None,
        )
        if str(result).strip().lower() not in {"ok.", "ok"}:
            raise RuntimeError(f"qBittorrent rejected the download: {result}")
