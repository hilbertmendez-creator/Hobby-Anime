"""Pure hybrid identity-mapping and idempotency logic for the AniList push feature.

All functions here are deterministic and free of HTTP/DB I/O: dependencies such as
a persisted manual override or AniList search candidates are always passed in by
the caller (orchestrator, Phase 5). This keeps the identity-resolution and
idempotency rules — the correctness-critical "skip on uncertain, never guess,
never decrease progress" contract — fully unit-testable without mocks.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from hobby_anime.library import normalize_title
from hobby_anime.models import AniListMatch, AniListPushCandidate, AniListPushReport, WatchedSeries

_SEASON_PART_MARKER = re.compile(
    r"\b(?:season|part|cour)\s*\d+\b"
    r"|\bs\d{1,2}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\s+season\b",
    re.IGNORECASE,
)


def normalize_match_title(value: str) -> str:
    """Normalize a title for identity matching.

    Extends `library.normalize_title` (case/punctuation/whitespace-insensitive)
    by also stripping common season/part markers (e.g. "Season 2", "Part 2",
    "S2", "2nd Season") so equivalent-series titles compare consistently.
    Deterministic: same input always yields the same output.
    """
    without_markers = _SEASON_PART_MARKER.sub(" ", value)
    return normalize_title(without_markers)


def resolve_media_id(
    series: WatchedSeries,
    override: Mapping[str, int | None] | None,
    matches: Sequence[AniListMatch],
    *,
    series_year: int | None = None,
) -> tuple[int | None, str, str]:
    """Resolve a Jellyfin series to an AniList media id using the skip-on-uncertain rule.

    Resolution order:
      1. A persisted manual override ALWAYS wins when present -> ("override", "").
      2. Otherwise, among candidates whose normalized title matches the series
         (and whose year agrees with `series_year` when both are known), accept
         a match ONLY if exactly one candidate remains -> ("auto", "").
      3. Otherwise (zero matches, multiple ambiguous matches, or year
         disagreement) -> (None, "", "unmapped"). Never guess.
    """
    if override is not None:
        override_id = override.get("override_media_id")
        if override_id is not None:
            return override_id, "override", ""

    target = normalize_match_title(series.name)
    candidates = [match for match in matches if normalize_match_title(match.title) == target]

    if series_year is not None:
        year_agreeing = [c for c in candidates if c.year is not None and c.year == series_year]
        if year_agreeing:
            candidates = year_agreeing
        else:
            candidates = [c for c in candidates if c.year is None]

    if len(candidates) == 1:
        return candidates[0].media_id, "auto", ""
    return None, "", "unmapped"


def decide_target(series: WatchedSeries, *, progress_mode: bool) -> tuple[str, int]:
    """Compute the intended AniList (status, progress) target for a series.

    Fully-watched series are always `COMPLETED` with the total episode count.
    Otherwise, in progress mode, the target is `CURRENT` with the watched
    episode count. Callers filter out partial series in non-progress mode
    before invoking this function, per the "default mode pushes only
    completed series" contract.
    """
    if series.total_episodes > 0 and series.watched_episodes >= series.total_episodes:
        return "COMPLETED", series.total_episodes
    return "CURRENT", series.watched_episodes


def needs_push(
    target_status: str,
    target_progress: int,
    current: tuple[str, int] | None,
) -> bool:
    """True when a mutation should be issued to reach the intended target.

    False when AniList's current entry already matches the target status and
    progress (skipped-unchanged), or when pushing would decrease progress
    below what AniList already reports (progress must never go backwards).
    """
    if current is None:
        return True
    current_status, current_progress = current
    if current_progress > target_progress:
        return False
    return not (current_status == target_status and current_progress == target_progress)


def build_report(
    candidates: Sequence[AniListPushCandidate],
    *,
    executed: bool = False,
    errors: Sequence[str] = (),
) -> AniListPushReport:
    """Aggregate a sequence of push candidates into a summary report.

    Candidates are classified by their `skip_reason`: "unmapped" and
    "unchanged" map to their respective skip counters, "failed" maps to the
    failure counter, and an empty `skip_reason` counts as pushed. `executed`
    reflects whether mutations were actually attempted for this batch
    (False for a dry-run preview); `errors` carries per-item failure detail.
    """
    pushed = 0
    skipped_unchanged = 0
    skipped_unmapped = 0
    failed = 0
    for candidate in candidates:
        if candidate.skip_reason == "unmapped":
            skipped_unmapped += 1
        elif candidate.skip_reason == "unchanged":
            skipped_unchanged += 1
        elif candidate.skip_reason == "failed":
            failed += 1
        else:
            pushed += 1
    return AniListPushReport(
        pushed=pushed,
        skipped_unchanged=skipped_unchanged,
        skipped_unmapped=skipped_unmapped,
        failed=failed,
        candidates=tuple(candidates),
        errors=tuple(errors),
        executed=executed,
    )
