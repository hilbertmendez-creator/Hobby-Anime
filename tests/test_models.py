from dataclasses import FrozenInstanceError

import pytest

from hobby_anime.models import WatchedEpisode, WatchedSeries


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
