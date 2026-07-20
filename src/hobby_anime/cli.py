from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict

from hobby_anime.anilist_oauth import run_auth_flow
from hobby_anime.anilist_push import run_push
from hobby_anime.config import Settings
from hobby_anime.daily import run_daily
from hobby_anime.database import TrackingDatabase
from hobby_anime.doctor import run_checks
from hobby_anime.jellyfin_client import JellyfinClient
from hobby_anime.library import audit_library
from hobby_anime.library_import import run_pending_imports
from hobby_anime.manual_review import approve_rejection, list_rejections
from hobby_anime.monthly import run_monthly
from hobby_anime.scheduler import start_scheduler
from hobby_anime.verification import run_verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hobby-Anime media automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily_parser = subparsers.add_parser("daily", help="Read RSS feeds and enqueue matching items")
    daily_parser.add_argument("--dry-run", action="store_true", help="Do not send items to qBittorrent")
    subparsers.add_parser("verify", help="Verify completed downloads with the Spanish policy")
    subparsers.add_parser("import", help="Retry verified downloads pending Sonarr import")
    subparsers.add_parser("monthly", help="Audit the library and create a discovery report")
    subparsers.add_parser("scheduler", help="Run all automation jobs continuously")
    subparsers.add_parser("init-db", help="Create or upgrade the local database")
    subparsers.add_parser("audit", help="Print the detected local media catalog")
    subparsers.add_parser("status", help="Show RSS, verification, and import counters")
    subparsers.add_parser("doctor", help="Check storage and internal service connectivity")
    rejections_parser = subparsers.add_parser(
        "rejections", help="List downloads rejected by the language policy"
    )
    rejections_parser.add_argument(
        "--json", action="store_true", help="Emit the rejection list as JSON"
    )
    approve_parser = subparsers.add_parser(
        "approve", help="Force-promote one or more rejected downloads"
    )
    approve_parser.add_argument("hashes", nargs="+", help="Torrent hashes to approve")
    watched_parser = subparsers.add_parser(
        "watched", help="Show Jellyfin watched status per series"
    )
    watched_parser.add_argument(
        "--json", action="store_true", help="Emit the watched status as JSON"
    )
    watched_parser.add_argument(
        "--series", help="Include per-episode played flags for this series id"
    )
    subparsers.add_parser(
        "anilist-auth",
        help="Authorize Hobby-Anime with AniList via OAuth2 and store the token",
    )
    push_anilist_parser = subparsers.add_parser(
        "push-anilist",
        help="Push Jellyfin watched progress to AniList (dry-run by default)",
    )
    push_anilist_parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually mutate AniList list entries (default is dry-run preview only)",
    )
    push_anilist_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (still requires --execute)",
    )
    push_anilist_parser.add_argument(
        "--progress",
        action="store_true",
        help="Also push partially-watched series as CURRENT (default pushes only completed series)",
    )
    push_anilist_parser.add_argument(
        "--json", action="store_true", help="Emit the push report as JSON"
    )
    return parser


def _run_watched(settings: Settings, *, as_json: bool, series_id: str | None) -> int:
    try:
        if not settings.jellyfin_api_key:
            raise ValueError("JELLYFIN_API_KEY is required")
        if not settings.jellyfin_user_id:
            raise ValueError("JELLYFIN_USER_ID is required when JELLYFIN_API_KEY is set")
        client = JellyfinClient(
            settings.jellyfin_url,
            settings.jellyfin_api_key,
            settings.jellyfin_user_id,
            timeout_seconds=settings.request_timeout_seconds,
            library_id=settings.jellyfin_library_id,
        )
        series_entries = []
        for series in client.list_watched_series():
            entry = {
                "series_id": series.id,
                "series_name": series.name,
                "episodes_total": series.total_episodes,
                "episodes_watched": series.watched_episodes,
                "episodes": [],
            }
            if series_id and series_id == series.id:
                entry["episodes"] = [
                    {
                        "episode_id": episode.id,
                        "episode_name": episode.name,
                        "played": episode.played,
                    }
                    for episode in client.episodes(series.id)
                ]
            series_entries.append(entry)
    except Exception as exc:  # never leak the API key in error output
        message = str(exc)
        if as_json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(f"error: {message}")
        return 1

    if as_json:
        print(json.dumps({"series": series_entries}, ensure_ascii=False, indent=2))
    else:
        for entry in series_entries:
            print(
                f"{entry['series_name']}: "
                f"{entry['episodes_watched']}/{entry['episodes_total']}"
            )
    return 0


def _run_anilist_auth(settings: Settings) -> int:
    try:
        database = TrackingDatabase(settings.database_path)
        database.initialize()
        run_auth_flow(settings, database)
    except Exception as exc:  # never leak client secret/code/token in error output
        print(f"error: {exc}")
        return 1
    print("AniList authorization successful. Token stored.")
    return 0


def _run_push_anilist(
    settings: Settings,
    *,
    execute: bool,
    assume_yes: bool,
    progress_mode: bool,
    as_json: bool,
) -> int:
    try:
        database = TrackingDatabase(settings.database_path)
        database.initialize()
        report = run_push(
            settings,
            database,
            execute=execute,
            assume_yes=assume_yes,
            progress_mode=progress_mode,
        )
    except Exception as exc:  # never leak the client secret/token in error output
        message = str(exc)
        if as_json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(f"error: {message}")
        return 1

    if as_json:
        print(
            json.dumps(
                {
                    "executed": report.executed,
                    "pushed": report.pushed,
                    "skipped_unchanged": report.skipped_unchanged,
                    "skipped_unmapped": report.skipped_unmapped,
                    "failed": report.failed,
                    "errors": list(report.errors),
                    "candidates": [
                        {
                            "series_id": candidate.series_id,
                            "series_name": candidate.series_name,
                            "media_id": candidate.media_id,
                            "source": candidate.source,
                            "status": candidate.status,
                            "progress": candidate.progress,
                            "skip_reason": candidate.skip_reason,
                        }
                        for candidate in report.candidates
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        mode = "EXECUTED" if report.executed else "DRY-RUN (preview only)"
        print(f"push-anilist [{mode}]")
        for candidate in report.candidates:
            if candidate.skip_reason:
                print(f"{candidate.series_name}: skip ({candidate.skip_reason})")
            else:
                print(
                    f"{candidate.series_name}: {candidate.status} {candidate.progress} "
                    f"(media_id={candidate.media_id}, source={candidate.source})"
                )
        print(
            f"pushed={report.pushed} skipped_unchanged={report.skipped_unchanged} "
            f"skipped_unmapped={report.skipped_unmapped} failed={report.failed}"
        )
    return 1 if report.failed else 0


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    settings = Settings.from_env()

    if args.command == "daily":
        result = run_daily(settings, dry_run=args.dry_run)
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 1 if result.failed else 0
    if args.command == "monthly":
        print(run_monthly(settings))
        return 0
    if args.command == "verify":
        result = run_verification(settings)
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 1 if result.failed else 0
    if args.command == "import":
        result = run_pending_imports(settings)
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 1 if result.failed else 0
    if args.command == "scheduler":
        start_scheduler(settings)
        return 0
    if args.command == "init-db":
        TrackingDatabase(settings.database_path).initialize()
        print(f"Database ready: {settings.database_path}")
        return 0
    if args.command == "audit":
        items = [
            {
                "title": item.title,
                "path": str(item.path),
                "file_count": item.file_count,
                "latest_episode": item.latest_episode,
            }
            for item in audit_library(settings.media_path)
        ]
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        database = TrackingDatabase(settings.database_path)
        database.initialize()
        print(json.dumps(database.pipeline_summary(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "doctor":
        checks = run_checks(settings)
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(check["ok"] for check in checks.values()) else 1
    if args.command == "rejections":
        rejections = list_rejections(settings)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "torrent_hash": rejected.torrent_hash,
                            "name": rejected.name,
                            "reason": rejected.reason,
                            "content_path": str(rejected.content_path),
                            "updated_at": rejected.updated_at,
                        }
                        for rejected in rejections
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for rejected in rejections:
                print(
                    f"{rejected.torrent_hash[:12]}  {rejected.name}  ({rejected.reason})"
                )
        return 0
    if args.command == "watched":
        return _run_watched(settings, as_json=args.json, series_id=args.series)
    if args.command == "anilist-auth":
        return _run_anilist_auth(settings)
    if args.command == "push-anilist":
        return _run_push_anilist(
            settings,
            execute=args.execute,
            assume_yes=args.yes,
            progress_mode=args.progress,
            as_json=args.json,
        )
    if args.command == "approve":
        failures = 0
        for torrent_hash in args.hashes:
            try:
                rejected = approve_rejection(settings, torrent_hash)
                print(f"approved {torrent_hash}: {rejected.name}")
            except Exception as exc:  # per-hash resilience: one failure never aborts the rest
                failures += 1
                print(f"failed {torrent_hash}: {exc}")
        return 1 if failures else 0
    return 2
