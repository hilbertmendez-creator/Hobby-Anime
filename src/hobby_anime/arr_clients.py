from __future__ import annotations

from typing import Any

import requests


class ProwlarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def status(self) -> dict[str, Any]:
        return self._get("/api/v1/system/status")

    def applications(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/applications")

    def _get(self, path: str) -> Any:
        response = self.session.get(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json", "X-Api-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


class BazarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def status(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/api/system/status",
            headers={"Accept": "application/json", "X-Api-Key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
