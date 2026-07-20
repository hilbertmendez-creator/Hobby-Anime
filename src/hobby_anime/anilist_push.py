"""Push orchestrator for syncing Jellyfin watched progress to AniList.

Composes the read-only `JellyfinClient`, the pure identity/idempotency
logic in `anilist_mapping`, the mutating `AniListWriteClient`, and
`TrackingDatabase` (token + override mapping storage) into a batch push,
mirroring `cleanup.py`'s shape: dry-run by default, `execute`/`--yes`
gating, and per-item `try/except` isolation so one failing series never
aborts the rest of the batch.

`plan_push` performs read-only AniList calls (`search_media`,
`get_list_entry`) but NEVER calls `save_media_list_entry` — that mutation
only happens inside `run_push`, and only when `execute=True` and the batch
is confirmed.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable

import requests

from hobby_anime.anilist_mapping import build_report, decide_target, needs_push, resolve_media_id
from hobby_anime.anilist_oauth import token_is_valid
from hobby_anime.anilist_write import AniListWriteClient
from hobby_anime.jellyfin_client import JellyfinClient
from hobby_anime.models import AniListPushCandidate, AniListPushReport, WatchedSeries

# AniList's public rate limit is ~90 requests/minute; pace mutations at
# roughly 1 request every 0.7s to stay comfortably under it.
RATE_LIMIT_SECONDS = 0.7
MAX_RETRY_ATTEMPTS = 3


def select_pushable_series(
    series: list[WatchedSeries], *, progress_mode: bool
) -> list[WatchedSeries]:
    """Filter watched series to the current push scope.

    Default (non-progress) mode only considers fully-watched series
    (`watched_episodes >= total_episodes > 0`); progress mode additionally
    includes partially-watched series.
    """
    if progress_mode:
        return list(series)
    return [
        item
        for item in series
        if item.total_episodes > 0 and item.watched_episodes >= item.total_episodes
    ]


def plan_push(
    settings: Any,
    jellyfin_client: Any,
    anilist_client: Any,
    database: Any,
    *,
    progress_mode: bool = False,
) -> list[AniListPushCandidate]:
    """Read-only: resolve each in-scope series to an idempotency-checked candidate.

    Never calls `save_media_list_entry`. For every series: resolves the
    AniList media id via `resolve_media_id` (persisted override -> exactly-
    one auto search match -> skip-unmapped, never guessing), then, when
    resolved, queries the live AniList entry and applies `needs_push` to
    decide whether the series is already up to date (skip-unchanged) or
    should be pushed.
    """
    candidates: list[AniListPushCandidate] = []
    for series in select_pushable_series(
        jellyfin_client.list_watched_series(), progress_mode=progress_mode
    ):
        override = database.get_mapping(series.id)
        matches = anilist_client.search_media(series.name)
        media_id, source, skip_reason = resolve_media_id(series, override, matches)

        if media_id is None:
            candidates.append(
                AniListPushCandidate(
                    series_id=series.id,
                    series_name=series.name,
                    media_id=None,
                    source=source,
                    status="",
                    progress=0,
                    skip_reason=skip_reason or "unmapped",
                )
            )
            continue

        target_status, target_progress = decide_target(series, progress_mode=progress_mode)
        current = anilist_client.get_list_entry(media_id)
        push_needed = needs_push(target_status, target_progress, current)

        candidates.append(
            AniListPushCandidate(
                series_id=series.id,
                series_name=series.name,
                media_id=media_id,
                source=source,
                status=target_status,
                progress=target_progress,
                skip_reason="" if push_needed else "unchanged",
            )
        )
    return candidates


def _retry_after_seconds(response: Any, attempt: int) -> float:
    """Read a `Retry-After` header if present, else fall back to exponential backoff."""
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return float(2**attempt)


def _push_one(
    anilist_client: Any,
    candidate: AniListPushCandidate,
    *,
    sleep: Callable[[float], None],
) -> None:
    """Issue the mutation for one candidate, retrying on HTTP 429 with backoff."""
    attempt = 0
    while True:
        try:
            anilist_client.save_media_list_entry(
                candidate.media_id, candidate.status, candidate.progress
            )
            return
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code != 429 or attempt >= MAX_RETRY_ATTEMPTS:
                raise
            sleep(_retry_after_seconds(response, attempt))
            attempt += 1


def run_push(
    settings: Any,
    database: Any,
    *,
    execute: bool = False,
    assume_yes: bool = False,
    progress_mode: bool = False,
    confirm: Callable[[str], str] = input,
    jellyfin_client: Any = None,
    anilist_client: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> AniListPushReport:
    """Orchestrate plan -> optional confirmation -> preview or mutate.

    Dry-run is the default: without `execute=True`, `save_media_list_entry`
    is never called and no confirmation prompt is shown. With
    `execute=True`, an interactive `y/N` confirmation is required unless
    `assume_yes=True` bypasses ONLY the prompt (never the `execute`
    requirement itself). Each candidate's mutation is isolated: a failure on
    one candidate is recorded and does not abort the rest of the batch.
    Requires a valid, non-expired stored AniList token; raises `ValueError`
    (directing the user to `anilist-auth`, never including the token value)
    when none is available.
    """
    token = database.get_token()
    if not token_is_valid(token):
        raise ValueError(
            "No valid AniList token found. Run 'hobby-anime anilist-auth' to authorize."
        )

    if jellyfin_client is None:
        jellyfin_client = JellyfinClient(
            settings.jellyfin_url,
            settings.jellyfin_api_key,
            settings.jellyfin_user_id,
            timeout_seconds=settings.request_timeout_seconds,
            library_id=settings.jellyfin_library_id,
        )
    if anilist_client is None:
        anilist_client = AniListWriteClient(
            token.access_token,
            url=settings.anilist_url,
            timeout_seconds=settings.request_timeout_seconds,
        )

    candidates = plan_push(
        settings, jellyfin_client, anilist_client, database, progress_mode=progress_mode
    )
    pushable = [c for c in candidates if not c.skip_reason]

    should_push = execute and bool(pushable)
    if should_push and not assume_yes:
        answer = confirm(f"Push {len(pushable)} series to AniList? [y/N] ")
        should_push = str(answer).strip().lower() == "y"

    final_candidates: list[AniListPushCandidate] = []
    errors: list[str] = []
    for candidate in candidates:
        if candidate.skip_reason or not should_push:
            final_candidates.append(candidate)
            continue
        try:
            _push_one(anilist_client, candidate, sleep=sleep)
            final_candidates.append(candidate)
        except Exception as exc:  # per-item isolation: never abort the batch
            errors.append(f"{candidate.series_name}: {exc}")
            final_candidates.append(replace(candidate, skip_reason="failed"))
        finally:
            sleep(RATE_LIMIT_SECONDS)

    return build_report(final_candidates, executed=should_push, errors=errors)
