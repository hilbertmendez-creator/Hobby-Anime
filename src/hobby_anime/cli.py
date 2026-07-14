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
from hobby_anime.monthly import run_monthly
from hobby_anime.scheduler import start_scheduler
from hobby_anime.verification import run_verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hobby-Anime media automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily_parser = subparsers.add_parser("daily", help="Read RSS feeds and enqueue matching items")
    daily_parser.add_argument("--dry-run", action="store_true", help="Do not send items to qBittorrent")
    subparsers.add_parser("verify", help="Verify completed downloads with the Spanish policy")
    subparsers.add_parser("monthly", help="Audit the library and create a discovery report")
    subparsers.add_parser("scheduler", help="Run daily and monthly jobs continuously")
    subparsers.add_parser("init-db", help="Create or upgrade the local database")
    subparsers.add_parser("audit", help="Print the detected local media catalog")
    subparsers.add_parser("doctor", help="Check storage and internal service connectivity")
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
    if args.command == "doctor":
        checks = run_checks(settings)
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(check["ok"] for check in checks.values()) else 1
    return 2
