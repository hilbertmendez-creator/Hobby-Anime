from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests


class SonarrCommandFailed(RuntimeError):
    pass


class SonarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.sleeper = sleeper

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
        }

    def status(self) -> dict[str, Any]:
        return self._get("/api/v3/system/status")

    def health(self) -> list[dict[str, Any]]:
        return self._get("/api/v3/health")

    def download_client_config(self) -> dict[str, Any]:
        return self._get("/api/v3/config/downloadclient")

    def root_folders(self) -> list[dict[str, Any]]:
        return self._get("/api/v3/rootfolder")

    def series(self) -> list[dict[str, Any]]:
        return self._get("/api/v3/series")

    def calendar(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        return self._get(
            "/api/v3/calendar",
            params={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "includeSeries": "true",
                "includeEpisodeFile": "true",
            },
        )

    def scan_verified(
        self,
        content_path: Path,
        verified_root: Path,
        download_client_id: str,
    ) -> int:
        resolved_path = content_path.resolve(strict=True)
        resolved_root = verified_root.resolve(strict=True)
        if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
            raise ValueError(f"Sonarr import path is outside verified storage: {content_path}")
        response = self.session.post(
            f"{self.base_url}/api/v3/command",
            json={
                "name": "DownloadedEpisodesScan",
                "path": str(resolved_path),
                "downloadClientId": download_client_id,
                "importMode": "copy",
            },
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        command_id = response.json().get("id")
        if command_id is None:
            raise RuntimeError("Sonarr did not return a command ID")
        return int(command_id)

    def command(self, command_id: int) -> dict[str, Any]:
        return self._get(f"/api/v3/command/{command_id}")

    def wait_for_command(
        self,
        command_id: int,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            command = self.command(command_id)
            status = str(command.get("status", "")).casefold()
            result = str(command.get("result", "")).casefold()
            if status == "completed":
                if result in {"unsuccessful", "failed"}:
                    raise SonarrCommandFailed(
                        str(command.get("message") or "Sonarr import was unsuccessful")
                    )
                return command
            if status in {"aborted", "cancelled", "failed"}:
                raise SonarrCommandFailed(
                    str(command.get("message") or f"Sonarr command {status}")
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for Sonarr command {command_id}")
            self.sleeper(poll_seconds)

    def _get(self, path: str, **kwargs: Any) -> Any:
        response = self.session.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            timeout=self.timeout_seconds,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
