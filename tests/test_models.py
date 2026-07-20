from dataclasses import FrozenInstanceError

import pytest

from hobby_anime.models import (
    AniListMatch,
    AniListPushCandidate,
    AniListPushReport,
    StoredToken,
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


def test_stored_token_is_frozen_with_expected_fields() -> None:
    token = StoredToken(
        access_token="secret-token",
        token_type="Bearer",
        obtained_at="2026-07-19T00:00:00+00:00",
        expires_at=None,
    )

    assert token.access_token == "secret-token"
    assert token.token_type == "Bearer"
    assert token.obtained_at == "2026-07-19T00:00:00+00:00"
    assert token.expires_at is None

    with pytest.raises(FrozenInstanceError):
        token.access_token = "other"  # type: ignore[misc]


def test_anilist_match_is_frozen_with_expected_fields() -> None:
    match = AniListMatch(media_id=101, title="Frieren", year=2023)

    assert match.media_id == 101
    assert match.title == "Frieren"
    assert match.year == 2023

    with pytest.raises(FrozenInstanceError):
        match.media_id = 999  # type: ignore[misc]


def test_anilist_push_candidate_is_frozen_with_expected_fields() -> None:
    candidate = AniListPushCandidate(
        series_id="s1",
        series_name="Frieren",
        media_id=101,
        source="auto",
        status="COMPLETED",
        progress=28,
        skip_reason="",
    )

    assert candidate.series_id == "s1"
    assert candidate.series_name == "Frieren"
    assert candidate.media_id == 101
    assert candidate.source == "auto"
    assert candidate.status == "COMPLETED"
    assert candidate.progress == 28
    assert candidate.skip_reason == ""

    with pytest.raises(FrozenInstanceError):
        candidate.media_id = 999  # type: ignore[misc]


def test_anilist_push_report_is_frozen_with_expected_fields() -> None:
    candidate = AniListPushCandidate(
        series_id="s1",
        series_name="Frieren",
        media_id=101,
        source="auto",
        status="COMPLETED",
        progress=28,
    )
    report = AniListPushReport(
        pushed=1,
        skipped_unchanged=0,
        skipped_unmapped=0,
        failed=0,
        candidates=(candidate,),
        errors=(),
    )

    assert report.pushed == 1
    assert report.skipped_unchanged == 0
    assert report.skipped_unmapped == 0
    assert report.failed == 0
    assert report.candidates == (candidate,)
    assert report.errors == ()

    with pytest.raises(FrozenInstanceError):
        report.pushed = 2  # type: ignore[misc]
