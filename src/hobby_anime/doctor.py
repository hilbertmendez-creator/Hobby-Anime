from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import requests

from hobby_anime.arr_clients import BazarrClient, ProwlarrClient
from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.qbittorrent_client import QBittorrentGateway
from hobby_anime.sonarr_client import SonarrClient


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

    if settings.sonarr_enabled:
        try:
            sonarr = SonarrClient(
                settings.sonarr_url,
                settings.sonarr_api_key,
                settings.request_timeout_seconds,
            )
            status = sonarr.status()
            checks["sonarr"] = {
                "ok": True,
                "detail": f"Version {status.get('version', 'unknown')}",
            }
            client_config = sonarr.download_client_config()
            completed_handling = bool(
                client_config.get("enableCompletedDownloadHandling", True)
            )
            checks["sonarr_import_policy"] = {
                "ok": not completed_handling,
                "detail": (
                    "Completed Download Handling is disabled"
                    if not completed_handling
                    else "Disable Completed Download Handling before using quarantine"
                ),
            }
            root_paths = {
                Path(str(root.get("path", "")))
                for root in sonarr.root_folders()
            }
            checks["sonarr_media_root"] = {
                "ok": settings.sonarr_media_root in root_paths,
                "detail": (
                    str(settings.sonarr_media_root)
                    if settings.sonarr_media_root in root_paths
                    else f"Missing Sonarr root folder: {settings.sonarr_media_root}"
                ),
            }
        except Exception as exc:
            checks["sonarr"] = {"ok": False, "detail": str(exc)}

    if settings.prowlarr_enabled:
        try:
            prowlarr = ProwlarrClient(
                settings.prowlarr_url,
                settings.prowlarr_api_key,
                settings.request_timeout_seconds,
            )
            status = prowlarr.status()
            applications = prowlarr.applications()
            sonarr_connected = any(
                "sonarr"
                in " ".join(
                    str(application.get(key, ""))
                    for key in ("name", "implementation", "implementationName")
                ).casefold()
                for application in applications
            )
            checks["prowlarr"] = {
                "ok": True,
                "detail": f"Version {status.get('version', 'unknown')}",
            }
            checks["prowlarr_sonarr"] = {
                "ok": sonarr_connected,
                "detail": (
                    "Sonarr application configured"
                    if sonarr_connected
                    else "Add Sonarr under Prowlarr applications"
                ),
            }
        except Exception as exc:
            checks["prowlarr"] = {"ok": False, "detail": str(exc)}

    if settings.bazarr_enabled:
        try:
            bazarr_status = BazarrClient(
                settings.bazarr_url,
                settings.bazarr_api_key,
                settings.request_timeout_seconds,
            ).status()
            checks["bazarr"] = {
                "ok": True,
                "detail": str(
                    bazarr_status.get("version")
                    or bazarr_status.get("bazarr_version")
                    or "Healthy"
                ),
            }
        except Exception as exc:
            checks["bazarr"] = {"ok": False, "detail": str(exc)}

    return checks
