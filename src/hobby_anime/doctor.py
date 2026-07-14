from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import requests

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.qbittorrent_client import QBittorrentGateway


def run_checks(settings: Settings) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}

    try:
        TrackingDatabase(settings.database_path).initialize()
        checks["database"] = {"ok": True, "detail": str(settings.database_path)}
    except Exception as exc:
        checks["database"] = {"ok": False, "detail": str(exc)}

    media_ok = settings.media_path.is_dir()
    checks["media"] = {
        "ok": media_ok,
        "detail": str(settings.media_path) if media_ok else f"Directory not found: {settings.media_path}",
    }

    quarantine_path = Path(settings.qbt_save_path)
    quarantine_ok = quarantine_path.is_dir()
    checks["quarantine"] = {
        "ok": quarantine_ok,
        "detail": (
            str(quarantine_path)
            if quarantine_ok
            else f"Directory not found: {quarantine_path}"
        ),
    }

    ffprobe_path = shutil.which(settings.ffprobe_path)
    checks["ffprobe"] = {
        "ok": ffprobe_path is not None,
        "detail": ffprobe_path or f"Executable not found: {settings.ffprobe_path}",
    }

    try:
        if not settings.qbt_password:
            raise ValueError("QBITTORRENT_PASSWORD is not configured")
        gateway = QBittorrentGateway(
            settings.qbt_host,
            settings.qbt_port,
            settings.qbt_username,
            settings.qbt_password,
            settings.qbt_save_path,
            settings.qbt_category,
        )
        version = gateway.connect()
        checks["qbittorrent"] = {"ok": True, "detail": f"Web API {version}"}
    except Exception as exc:
        checks["qbittorrent"] = {"ok": False, "detail": str(exc)}

    try:
        response = requests.get(
            f"{settings.jellyfin_url}/health",
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        checks["jellyfin"] = {"ok": True, "detail": response.text.strip() or "Healthy"}
    except Exception as exc:
        checks["jellyfin"] = {"ok": False, "detail": str(exc)}

    return checks
