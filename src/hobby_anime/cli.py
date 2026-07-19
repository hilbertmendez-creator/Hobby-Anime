from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict

from hobby_anime.config import Settings
from hobby_anime.daily import run_daily
from hobby_anime.database import TrackingDatabase
from hobby_anime.doctor import run_checks
from hobby_anime.library import audit_library
from hobby_anime.library_import import run_pending_imports
from hobby_anime.manual_review import ApprovalError, approve_rejection, list_rejections
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
    return parser


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
