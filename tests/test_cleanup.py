import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hobby_anime.cleanup import (
    delete_series,
    has_hardlinked_files,
    inspect_target,
    plan_cleanup,
    resolve_within_root,
    run_cleanup,
    select_complete_series,
)
from hobby_anime.config import Settings
from hobby_anime.models import CleanupCandidate, WatchedSeries


def _series(id_: str, name: str, total: int, watched: int) -> WatchedSeries:
    return WatchedSeries(id=id_, name=name, total_episodes=total, watched_episodes=watched)


class _FakeClient:
    def __init__(self, series: list[WatchedSeries], paths: dict[str, Path]) -> None:
        self._series = series
        self._paths = paths

    def list_watched_series(self) -> list[WatchedSeries]:
        return self._series

    def series_path(self, series_id: str) -> Path | None:
        return self._paths.get(series_id)


def _cleanup_settings(settings: Settings, root: Path) -> Settings:
    return replace(
        settings,
        jellyfin_api_key="key",
        jellyfin_user_id="user-1",
        sonarr_media_root=root,
    )


# --- select_complete_series --------------------------------------------------


def test_select_complete_series_includes_fully_watched() -> None:
    complete = _series("s1", "Frieren", total=28, watched=28)
    partial = _series("s2", "Solo Leveling", total=12, watched=5)

    result = select_complete_series([complete, partial])

    assert result == [complete]


def test_select_complete_series_returns_empty_when_none_complete() -> None:
    partial = _series("s2", "Solo Leveling", total=12, watched=5)

    result = select_complete_series([partial])

    assert result == []


# --- resolve_within_root ------------------------------------------------------


def test_resolve_within_root_accepts_path_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)

    resolved = resolve_within_root(series_dir, [root])

    assert resolved == series_dir.resolve()


def test_resolve_within_root_rejects_path_outside_all_roots(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "Frieren"
    outside.mkdir(parents=True)

    with pytest.raises(ValueError, match="outside"):
        resolve_within_root(outside, [root])


def test_resolve_within_root_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    traversal_path = root / ".." / "elsewhere"

    with pytest.raises(ValueError, match="outside"):
        resolve_within_root(traversal_path, [root])


def test_resolve_within_root_rejects_symlink_escaping_root(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link = root / "EscapedSeries"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires elevated privileges on this platform")

    with pytest.raises(ValueError, match="outside"):
        resolve_within_root(link, [root])


# --- has_hardlinked_files ------------------------------------------------------


def test_has_hardlinked_files_true_when_any_file_has_multiple_links(tmp_path: Path) -> None:
    series_dir = tmp_path / "Frieren"
    series_dir.mkdir()
    original = series_dir / "ep01.mkv"
    original.write_bytes(b"data")
    os.link(original, series_dir / "ep01-hardlink.mkv")

    assert has_hardlinked_files(series_dir) is True


def test_has_hardlinked_files_false_when_no_hardlinks(tmp_path: Path) -> None:
    series_dir = tmp_path / "Frieren"
    series_dir.mkdir()
    (series_dir / "ep01.mkv").write_bytes(b"data")

    assert has_hardlinked_files(series_dir) is False


# --- inspect_target ------------------------------------------------------------


def test_inspect_target_skips_hardlinked_without_force(tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    original = series_dir / "ep01.mkv"
    original.write_bytes(b"data")
    os.link(original, series_dir / "ep01-hardlink.mkv")

    candidate = inspect_target(
        series_dir, [root], series_id="s1", series_name="Frieren", force_hardlinks=False
    )

    assert candidate.status == "skipped"
    assert candidate.hardlinked is True
    assert candidate.series_id == "s1"
    assert candidate.series_name == "Frieren"


def test_inspect_target_deletable_when_hardlinked_and_forced(tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    original = series_dir / "ep01.mkv"
    original.write_bytes(b"data")
    os.link(original, series_dir / "ep01-hardlink.mkv")

    candidate = inspect_target(
        series_dir, [root], series_id="s1", series_name="Frieren", force_hardlinks=True
    )

    assert candidate.status == "deletable"
    assert candidate.hardlinked is True


def test_inspect_target_deletable_when_no_hardlinks(tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    candidate = inspect_target(
        series_dir, [root], series_id="s1", series_name="Frieren", force_hardlinks=False
    )

    assert candidate.status == "deletable"
    assert candidate.hardlinked is False


def test_inspect_target_reports_missing_path(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    missing = root / "GhostSeries"

    candidate = inspect_target(
        missing, [root], series_id="s1", series_name="Ghost Series", force_hardlinks=False
    )

    assert candidate.status == "skipped"
    assert candidate.reason == "missing"


def test_inspect_target_errors_when_boundary_check_fails(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "Frieren"
    outside.mkdir(parents=True)

    candidate = inspect_target(
        outside, [root], series_id="s1", series_name="Frieren", force_hardlinks=False
    )

    assert candidate.status == "error"
    assert "outside" in candidate.reason


# --- delete_series --------------------------------------------------------------


def test_delete_series_removes_directory(tmp_path: Path) -> None:
    series_dir = tmp_path / "Frieren"
    series_dir.mkdir()
    (series_dir / "ep01.mkv").write_bytes(b"data")
    candidate = CleanupCandidate(
        series_id="s1", series_name="Frieren", path=series_dir, status="deletable"
    )

    delete_series(candidate)

    assert not series_dir.exists()


# --- plan_cleanup ----------------------------------------------------------------


def test_plan_cleanup_chains_select_series_path_and_inspect(tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    complete = _series("s1", "Frieren", total=28, watched=28)
    partial = _series("s2", "Solo Leveling", total=12, watched=5)
    client = _FakeClient([complete, partial], {"s1": series_dir})
    settings = SimpleNamespace(sonarr_media_root=root, media_path=root)

    candidates = plan_cleanup(settings, client)

    assert len(candidates) == 1
    assert candidates[0].series_id == "s1"
    assert candidates[0].status == "deletable"


def test_plan_cleanup_skips_series_without_resolvable_path(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {})
    settings = SimpleNamespace(sonarr_media_root=root, media_path=root)

    candidates = plan_cleanup(settings, client)

    assert len(candidates) == 1
    assert candidates[0].status == "skipped"
    assert candidates[0].reason == "no_path"


# --- run_cleanup -------------------------------------------------------------------


def test_run_cleanup_dry_run_deletes_nothing(settings: Settings) -> None:
    root = settings.media_path
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": series_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=False, client=client)

    assert report.executed is False
    assert series_dir.exists()
    assert report.freed_bytes == 0


def test_run_cleanup_execute_without_confirmation_aborts(settings: Settings) -> None:
    root = settings.media_path
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": series_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=True, client=client, confirm=lambda _: "n")

    assert report.executed is False
    assert series_dir.exists()


def test_run_cleanup_yes_without_execute_still_previews(settings: Settings) -> None:
    root = settings.media_path
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": series_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=False, assume_yes=True, client=client)

    assert report.executed is False
    assert series_dir.exists()


def test_run_cleanup_execute_with_yes_deletes(settings: Settings) -> None:
    root = settings.media_path
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": series_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=True, assume_yes=True, client=client)

    assert report.executed is True
    assert not series_dir.exists()
    assert report.freed_bytes > 0


def test_run_cleanup_hardlinked_skipped_without_force(settings: Settings) -> None:
    root = settings.media_path
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    original = series_dir / "ep01.mkv"
    original.write_bytes(b"data")
    os.link(original, series_dir / "ep01-hardlink.mkv")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": series_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=True, assume_yes=True, client=client)

    assert series_dir.exists()
    assert report.skipped == 1
    assert report.freed_bytes == 0


def test_run_cleanup_hardlinked_deleted_with_force(settings: Settings) -> None:
    root = settings.media_path
    series_dir = root / "Frieren"
    series_dir.mkdir(parents=True)
    original = series_dir / "ep01.mkv"
    original.write_bytes(b"data")
    os.link(original, series_dir / "ep01-hardlink.mkv")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": series_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(
        cleanup_settings, execute=True, assume_yes=True, force_hardlinks=True, client=client
    )

    assert not series_dir.exists()
    assert report.freed_bytes > 0


def test_run_cleanup_path_outside_root_never_deleted(settings: Settings) -> None:
    root = settings.media_path
    outside = root.parent / "elsewhere" / "Frieren"
    outside.mkdir(parents=True)
    (outside / "ep01.mkv").write_bytes(b"data")

    complete = _series("s1", "Frieren", total=28, watched=28)
    client = _FakeClient([complete], {"s1": outside})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=True, assume_yes=True, client=client)

    assert outside.exists()
    assert report.errors == 1


def test_run_cleanup_isolates_per_item_failure(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    import hobby_anime.cleanup as cleanup_module

    root = settings.media_path
    dir1 = root / "Frieren"
    dir1.mkdir(parents=True)
    (dir1 / "ep01.mkv").write_bytes(b"data")
    dir2 = root / "SoloLeveling"
    dir2.mkdir(parents=True)
    (dir2 / "ep01.mkv").write_bytes(b"data")

    s1 = _series("s1", "Frieren", total=28, watched=28)
    s2 = _series("s2", "Solo Leveling", total=12, watched=12)
    client = _FakeClient([s1, s2], {"s1": dir1, "s2": dir2})
    cleanup_settings = _cleanup_settings(settings, root)

    original_delete = cleanup_module.delete_series

    def flaky_delete(candidate: CleanupCandidate) -> None:
        if candidate.series_id == "s1":
            raise OSError("permission denied")
        original_delete(candidate)

    monkeypatch.setattr(cleanup_module, "delete_series", flaky_delete)

    report = cleanup_module.run_cleanup(
        cleanup_settings, execute=True, assume_yes=True, client=client
    )

    assert dir1.exists()
    assert not dir2.exists()
    assert report.errors == 1


def test_run_cleanup_freed_bytes_only_counts_actually_deleted(settings: Settings) -> None:
    root = settings.media_path
    deletable_dir = root / "Frieren"
    deletable_dir.mkdir(parents=True)
    (deletable_dir / "ep01.mkv").write_bytes(b"x" * 100)

    hardlinked_dir = root / "SoloLeveling"
    hardlinked_dir.mkdir(parents=True)
    original = hardlinked_dir / "ep01.mkv"
    original.write_bytes(b"y" * 200)
    os.link(original, hardlinked_dir / "ep01-hardlink.mkv")

    s1 = _series("s1", "Frieren", total=28, watched=28)
    s2 = _series("s2", "Solo Leveling", total=12, watched=12)
    client = _FakeClient([s1, s2], {"s1": deletable_dir, "s2": hardlinked_dir})
    cleanup_settings = _cleanup_settings(settings, root)

    report = run_cleanup(cleanup_settings, execute=True, assume_yes=True, client=client)

    assert report.freed_bytes == 100
