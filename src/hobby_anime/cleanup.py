"""Selection/safety logic and orchestration for disk cleanup of fully-watched
series.

The pure functions (`select_complete_series`, `resolve_within_root`,
`has_hardlinked_files`, `inspect_target`) perform no filesystem mutation and
are safe to call repeatedly against `tmp_path` in tests. `delete_series` is
the ONLY function in this module allowed to mutate the filesystem, and it
must only be called after `inspect_target` has classified a candidate as
"deletable" (full safety gate: boundary -> existence -> hardlink already
passed).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from hobby_anime.jellyfin_client import JellyfinClient
from hobby_anime.models import CleanupCandidate, CleanupReport, WatchedSeries


def select_complete_series(series: list[WatchedSeries]) -> list[WatchedSeries]:
    """Return only series where every episode has been watched."""
    return [item for item in series if item.watched_episodes == item.total_episodes]


def resolve_within_root(candidate: Path, roots: Sequence[Path]) -> Path:
    """Resolve `candidate` to a real path and assert it lies inside a root.

    Uses `os.path.realpath` so symlinked components and `../` traversal are
    fully resolved before the boundary check runs; a resolved path outside
    every root raises `ValueError` regardless of the symbolic form of the
    input path.
    """
    resolved = Path(os.path.realpath(candidate))
    for root in roots:
        resolved_root = Path(os.path.realpath(root))
        if resolved == resolved_root or resolved.is_relative_to(resolved_root):
            return resolved
    raise ValueError(f"{candidate} resolves outside all configured roots: {list(roots)}")


def has_hardlinked_files(path: Path) -> bool:
    """Return True if any regular file under `path` has a link count > 1."""
    if path.is_file():
        return os.stat(path).st_nlink > 1
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if os.stat(file_path).st_nlink > 1:
                return True
    return False


def inspect_target(
    path: Path,
    roots: Sequence[Path],
    *,
    series_id: str = "",
    series_name: str = "",
    force_hardlinks: bool = False,
) -> CleanupCandidate:
    """Compose boundary → existence → hardlink checks into a `CleanupCandidate`.

    Symlink escape is handled inside `resolve_within_root` (realpath already
    resolves symlinked components before the boundary check runs).
    """
    try:
        resolved = resolve_within_root(path, roots)
    except ValueError as exc:
        return CleanupCandidate(
            series_id=series_id,
            series_name=series_name,
            path=path,
            status="error",
            reason=str(exc),
        )

    if not resolved.exists():
        return CleanupCandidate(
            series_id=series_id,
            series_name=series_name,
            path=resolved,
            status="skipped",
            reason="missing",
        )

    hardlinked = has_hardlinked_files(resolved)
    if hardlinked and not force_hardlinks:
        return CleanupCandidate(
            series_id=series_id,
            series_name=series_name,
            path=resolved,
            status="skipped",
            reason="hardlinked",
            hardlinked=True,
        )

    return CleanupCandidate(
        series_id=series_id,
        series_name=series_name,
        path=resolved,
        status="deletable",
        hardlinked=hardlinked,
    )


def delete_series(candidate: CleanupCandidate) -> None:
    """Permanently remove a candidate's directory. The ONLY mutating function
    in this module.

    Callers MUST ensure `candidate.status == "deletable"` (i.e. the full
    safety gate in `inspect_target` already passed: boundary, existence, and
    hardlink checks) before calling this. It performs no re-validation of
    its own.
    """
    shutil.rmtree(candidate.path)


def _directory_size(path: Path) -> int:
    """Sum file sizes under `path` (or a single file's size). Best-effort:
    files that vanish mid-walk are skipped rather than raising."""
    if path.is_file():
        return os.stat(path).st_size
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                total += os.stat(file_path).st_size
            except OSError:
                continue
    return total


def plan_cleanup(
    settings: Any,
    client: Any,
    *,
    force_hardlinks: bool = False,
) -> list[CleanupCandidate]:
    """Read-only: compose watched-series data into inspected candidates.

    Chains `client.list_watched_series()` -> `select_complete_series()` ->
    `client.series_path()` -> `inspect_target()`. Performs no filesystem
    mutation. Series whose on-disk path cannot be resolved are reported as
    skipped (`reason="no_path"`) rather than raising.
    """
    roots = [settings.sonarr_media_root, settings.media_path]
    candidates: list[CleanupCandidate] = []
    for series in select_complete_series(client.list_watched_series()):
        path = client.series_path(series.id)
        if path is None:
            candidates.append(
                CleanupCandidate(
                    series_id=series.id,
                    series_name=series.name,
                    path=Path(""),
                    status="skipped",
                    reason="no_path",
                )
            )
            continue
        candidates.append(
            inspect_target(
                path,
                roots,
                series_id=series.id,
                series_name=series.name,
                force_hardlinks=force_hardlinks,
            )
        )
    return candidates


def run_cleanup(
    settings: Any,
    *,
    execute: bool = False,
    force_hardlinks: bool = False,
    assume_yes: bool = False,
    confirm: Callable[[str], str] = input,
    client: Any = None,
) -> CleanupReport:
    """Orchestrate plan -> optional confirmation -> preview or delete.

    Dry-run is the default: without `execute=True` nothing is ever deleted
    and no confirmation prompt is shown. With `execute=True`, an interactive
    `y/N` confirmation is required unless `assume_yes=True` bypasses ONLY the
    prompt (never the `execute` requirement itself). Each candidate's
    deletion is isolated: an `OSError` on one candidate is recorded as a
    failed item and does not abort the rest of the batch. `freed_bytes` on
    the report only counts space for series that were ACTUALLY deleted (not
    hardlink-skipped, dry-run-previewed, or failed).
    """
    if client is None:
        client = JellyfinClient(
            settings.jellyfin_url,
            settings.jellyfin_api_key,
            settings.jellyfin_user_id,
            timeout_seconds=settings.request_timeout_seconds,
            library_id=settings.jellyfin_library_id,
        )

    candidates = plan_cleanup(settings, client, force_hardlinks=force_hardlinks)
    deletable = [c for c in candidates if c.status == "deletable"]

    should_delete = execute and bool(deletable)
    if should_delete and not assume_yes:
        answer = confirm(f"Delete {len(deletable)} series? [y/N] ")
        should_delete = str(answer).strip().lower() == "y"

    final_items: list[CleanupCandidate] = []
    freed_bytes = 0
    for candidate in candidates:
        if candidate.status != "deletable" or not should_delete:
            final_items.append(candidate)
            continue
        try:
            size = _directory_size(candidate.path)
            delete_series(candidate)
            freed_bytes += size
            final_items.append(replace(candidate, status="deleted", freed_bytes=size))
        except OSError as exc:
            final_items.append(replace(candidate, status="failed", reason=str(exc)))

    return CleanupReport(
        executed=should_delete,
        deletable=sum(1 for c in final_items if c.status in ("deletable", "deleted")),
        skipped=sum(1 for c in final_items if c.status == "skipped"),
        errors=sum(1 for c in final_items if c.status in ("error", "failed")),
        freed_bytes=freed_bytes,
        items=tuple(final_items),
    )
