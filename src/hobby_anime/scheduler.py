from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from hobby_anime.config import Settings
from hobby_anime.daily import run_daily
from hobby_anime.monthly import run_monthly
from hobby_anime.verification import run_verification

LOGGER = logging.getLogger(__name__)


def start_scheduler(settings: Settings) -> None:
    settings.validate_schedule()
    timezone = ZoneInfo(settings.timezone)
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        run_daily,
        "cron",
        kwargs={"settings": settings},
        hour=settings.daily_hour,
        minute=settings.daily_minute,
        id="daily-rss-agent",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3_600,
    )
    scheduler.add_job(
        run_verification,
        "interval",
        kwargs={"settings": settings},
        minutes=settings.verification_interval_minutes,
        id="completed-download-verifier",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        run_monthly,
        "cron",
        kwargs={"settings": settings},
        day=settings.monthly_day,
        hour=settings.monthly_hour,
        minute=0,
        id="monthly-discovery-agent",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86_400,
    )
    LOGGER.info(
        "Scheduler started (%s): daily=%02d:%02d verify_every=%dm monthly=day %d at %02d:00",
        settings.timezone,
        settings.daily_hour,
        settings.daily_minute,
        settings.verification_interval_minutes,
        settings.monthly_day,
        settings.monthly_hour,
    )
    scheduler.start()
