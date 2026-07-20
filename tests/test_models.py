from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from hobby_anime.models import (
    CleanupCandidate,
    CleanupReport,
    WatchedEpisode,
    WatchedSeries,
)


def test_watched_series_is_frozen_with_expected_fields() -> None:
    series = WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=12)

    assert series.id == "s1"
    assert series.name == "Frieren"
    assert series.total_episodes == 28
    assert series.watched_episodes == 12
    assert series == WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=12)

    with pytest.raises(FrozenInstanceError):
        series.watched_episodes = 13  # type: ignore[misc]


def test_watched_episode_is_frozen_with_expected_fields() -> None:
    episode = WatchedEpisode(id="e1", name="Episode 1", played=True)

    assert episode.id == "e1"
    assert episode.name == "Episode 1"
    assert episode.played is True
    assert episode == WatchedEpisode(id="e1", name="Episode 1", played=True)

    with pytest.raises(FrozenInstanceError):
        episode.played = False  # type: ignore[misc]


def test_cleanup_candidate_is_frozen_with_expected_fields() -> None:
    candidate = CleanupCandidate(
        series_id="s1",
        series_name="Frieren",
        path=Path("/data/media/anime/Frieren"),
        status="deletable",
    )

    assert candidate.series_id == "s1"
    assert candidate.series_name == "Frieren"
    assert candidate.path == Path("/data/media/anime/Frieren")
    assert candidate.status == "deletable"
    assert candidate.reason == ""
    assert candidate.freed_bytes == 0
    assert candidate.hardlinked is False

    with pytest.raises(FrozenInstanceError):
        candidate.status = "skipped"  # type: ignore[misc]


def test_cleanup_report_is_frozen_with_expected_fields() -> None:
    candidate = CleanupCandidate(
        series_id="s1",
        series_name="Frieren",
        path=Path("/data/media/anime/Frieren"),
        status="deletable",
        freed_bytes=1024,
    )
    report = CleanupReport(
        executed=False,
        deletable=1,
        skipped=0,
        errors=0,
        freed_bytes=1024,
        items=(candidate,),
    )

    assert report.executed is False
    assert report.deletable == 1
    assert report.skipped == 0
    assert report.errors == 0
    assert report.freed_bytes == 1024
    assert report.items == (candidate,)

    with pytest.raises(FrozenInstanceError):
        report.executed = True  # type: ignore[misc]
