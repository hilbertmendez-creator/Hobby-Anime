from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import requests

from hobby_anime.anilist_push import plan_push, run_push
from hobby_anime.models import AniListMatch, StoredToken, WatchedSeries

VALID_TOKEN = StoredToken(
    access_token="top-secret-anilist-access-token",  # noqa: S106
    token_type="Bearer",
    obtained_at=datetime.now(UTC).isoformat(),
    expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
)

EXPIRED_TOKEN = StoredToken(
    access_token="top-secret-expired-token",  # noqa: S106
    token_type="Bearer",
    obtained_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
    expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
)


class FakeDatabase:
    def __init__(self, token: StoredToken | None = None, mappings: dict | None = None) -> None:
        self._token = token
        self._mappings = mappings or {}

    def get_token(self) -> StoredToken | None:
        return self._token

    def get_mapping(self, series_id: str) -> dict | None:
        return self._mappings.get(series_id)


class FakeJellyfinClient:
    def __init__(self, series: list[WatchedSeries]) -> None:
        self._series = series

    def list_watched_series(self) -> list[WatchedSeries]:
        return self._series


class FakeAniListClient:
    def __init__(
        self,
        matches: dict[str, list[AniListMatch]] | None = None,
        entries: dict[int, tuple[str, int] | None] | None = None,
        save_side_effects: dict[int, Exception] | None = None,
    ) -> None:
        self._matches = matches or {}
        self._entries = entries or {}
        self._save_side_effects = save_side_effects or {}
        self.search_calls: list[str] = []
        self.get_entry_calls: list[int] = []
        self.save_calls: list[tuple[int, str, int]] = []

    def search_media(self, title: str) -> list[AniListMatch]:
        self.search_calls.append(title)
        return self._matches.get(title, [])

    def get_list_entry(self, media_id: int) -> tuple[str, int] | None:
        self.get_entry_calls.append(media_id)
        return self._entries.get(media_id)

    def save_media_list_entry(self, media_id: int, status: str, progress: int):
        self.save_calls.append((media_id, status, progress))
        if media_id in self._save_side_effects:
            raise self._save_side_effects[media_id]
        return (status, progress)


FRIEREN = WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=28)
PARTIAL = WatchedSeries(id="s2", name="Ongoing Show", total_episodes=24, watched_episodes=5)
UNMATCHABLE = WatchedSeries(id="s3", name="Nonexistent Show", total_episodes=12, watched_episodes=12)


def _no_sleep(_seconds: float) -> None:
    pass


# --- plan_push: read-only, never mutates ---


def test_plan_push_never_calls_save_media_list_entry() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase(mappings={})

    plan_push(None, jellyfin, anilist, database)

    assert anilist.save_calls == []


def test_plan_push_default_mode_only_considers_complete_series() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN, PARTIAL])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase()

    candidates = plan_push(None, jellyfin, anilist, database, progress_mode=False)

    assert [c.series_id for c in candidates] == ["s1"]


def test_plan_push_progress_mode_includes_partial_series() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN, PARTIAL])
    anilist = FakeAniListClient(
        matches={
            "Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)],
            "Ongoing Show": [AniListMatch(media_id=202, title="Ongoing Show", year=2024)],
        },
        entries={101: None, 202: None},
    )
    database = FakeDatabase()

    candidates = plan_push(None, jellyfin, anilist, database, progress_mode=True)

    assert {c.series_id for c in candidates} == {"s1", "s2"}
    partial_candidate = next(c for c in candidates if c.series_id == "s2")
    assert partial_candidate.status == "CURRENT"
    assert partial_candidate.progress == 5


def test_plan_push_unmapped_series_skipped_never_guesses() -> None:
    jellyfin = FakeJellyfinClient([UNMATCHABLE])
    anilist = FakeAniListClient(matches={"Nonexistent Show": []})
    database = FakeDatabase()

    candidates = plan_push(None, jellyfin, anilist, database)

    assert len(candidates) == 1
    assert candidates[0].media_id is None
    assert candidates[0].skip_reason == "unmapped"
    assert anilist.get_entry_calls == []


def test_plan_push_idempotent_entry_marks_skip_unchanged() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: ("COMPLETED", 28)},
    )
    database = FakeDatabase()

    candidates = plan_push(None, jellyfin, anilist, database)

    assert candidates[0].skip_reason == "unchanged"


def test_plan_push_override_mapping_wins_over_search() -> None:
    jellyfin = FakeJellyfinClient([UNMATCHABLE])
    anilist = FakeAniListClient(entries={999: None})
    database = FakeDatabase(mappings={"s3": {"override_media_id": 999, "auto_media_id": None}})

    candidates = plan_push(None, jellyfin, anilist, database)

    assert candidates[0].media_id == 999
    assert candidates[0].source == "override"
    assert candidates[0].skip_reason == ""


# --- run_push: dry-run default safety ---


def test_run_push_dry_run_default_issues_zero_mutations() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=False,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert anilist.save_calls == []
    assert report.executed is False
    assert report.pushed == 1  # would-be-pushed, previewed only


def test_run_push_execute_without_confirmation_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=False,
        confirm=lambda _prompt: "no",
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert anilist.save_calls == []
    assert report.executed is False


def test_run_push_execute_with_yes_pushes() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert anilist.save_calls == [(101, "COMPLETED", 28)]
    assert report.executed is True
    assert report.pushed == 1
    assert report.failed == 0


def test_run_push_idempotent_skip_issues_no_mutation() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: ("COMPLETED", 28)},
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert anilist.save_calls == []
    assert report.skipped_unchanged == 1


def test_run_push_unmapped_series_never_pushed() -> None:
    jellyfin = FakeJellyfinClient([UNMATCHABLE])
    anilist = FakeAniListClient(matches={"Nonexistent Show": []})
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert anilist.save_calls == []
    assert report.skipped_unmapped == 1


def test_run_push_per_item_failure_isolation() -> None:
    other = WatchedSeries(id="s4", name="Other Show", total_episodes=10, watched_episodes=10)
    jellyfin = FakeJellyfinClient([FRIEREN, other])
    anilist = FakeAniListClient(
        matches={
            "Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)],
            "Other Show": [AniListMatch(media_id=202, title="Other Show", year=2021)],
        },
        entries={101: None, 202: None},
        save_side_effects={101: RuntimeError("boom")},
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert report.failed == 1
    assert report.pushed == 1
    assert (202, "COMPLETED", 10) in anilist.save_calls
    assert len(report.errors) == 1
    assert "Frieren" in report.errors[0]


def test_run_push_missing_token_fails_loud_without_leaking_secret() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient()
    database = FakeDatabase(token=None)

    with pytest.raises(ValueError) as excinfo:
        run_push(
            None,
            database,
            execute=True,
            assume_yes=True,
            jellyfin_client=jellyfin,
            anilist_client=anilist,
            sleep=_no_sleep,
        )

    assert "anilist-auth" in str(excinfo.value)
    assert jellyfin.list_watched_series is not None
    assert anilist.search_calls == []
    assert anilist.save_calls == []


def test_run_push_expired_token_fails_loud() -> None:
    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FakeAniListClient()
    database = FakeDatabase(token=EXPIRED_TOKEN)

    with pytest.raises(ValueError) as excinfo:
        run_push(
            None,
            database,
            execute=True,
            assume_yes=True,
            jellyfin_client=jellyfin,
            anilist_client=anilist,
            sleep=_no_sleep,
        )

    assert EXPIRED_TOKEN.access_token not in str(excinfo.value)
    assert anilist.save_calls == []


def test_run_push_paces_requests_between_mutations() -> None:
    other = WatchedSeries(id="s4", name="Other Show", total_episodes=10, watched_episodes=10)
    jellyfin = FakeJellyfinClient([FRIEREN, other])
    anilist = FakeAniListClient(
        matches={
            "Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)],
            "Other Show": [AniListMatch(media_id=202, title="Other Show", year=2021)],
        },
        entries={101: None, 202: None},
    )
    database = FakeDatabase(token=VALID_TOKEN)
    sleeps: list[float] = []

    run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=sleeps.append,
    )

    assert len(sleeps) == 2
    assert all(value == pytest.approx(0.7) for value in sleeps)


class _FakeHTTPResponse:
    def __init__(self, status_code: int, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


def test_run_push_retries_on_429_honoring_retry_after() -> None:
    response = _FakeHTTPResponse(429, headers={"Retry-After": "5"})
    error = requests.HTTPError("429 rate limited")
    error.response = response

    class FlakyAniListClient(FakeAniListClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._attempts = 0

        def save_media_list_entry(self, media_id: int, status: str, progress: int):
            self._attempts += 1
            self.save_calls.append((media_id, status, progress))
            if self._attempts == 1:
                raise error
            return (status, progress)

    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = FlakyAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase(token=VALID_TOKEN)
    sleeps: list[float] = []

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=sleeps.append,
    )

    assert report.failed == 0
    assert report.pushed == 1
    assert 5.0 in sleeps
    assert len(anilist.save_calls) == 2


def test_run_push_gives_up_after_max_retries_and_marks_failed() -> None:
    response = _FakeHTTPResponse(429, headers={})

    class AlwaysRateLimitedClient(FakeAniListClient):
        def save_media_list_entry(self, media_id: int, status: str, progress: int):
            self.save_calls.append((media_id, status, progress))
            error = requests.HTTPError("429 rate limited")
            error.response = response
            raise error

    jellyfin = FakeJellyfinClient([FRIEREN])
    anilist = AlwaysRateLimitedClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: None},
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(
        None,
        database,
        execute=True,
        assume_yes=True,
        jellyfin_client=jellyfin,
        anilist_client=anilist,
        sleep=_no_sleep,
    )

    assert report.failed == 1
    assert report.pushed == 0
    assert len(report.errors) == 1


def test_run_push_constructs_default_clients_when_none_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hobby_anime.config import Settings

    fake_jellyfin = FakeJellyfinClient([FRIEREN])
    fake_anilist = FakeAniListClient(
        matches={"Frieren": [AniListMatch(media_id=101, title="Frieren", year=2023)]},
        entries={101: ("COMPLETED", 28)},
    )

    monkeypatch.setattr(
        "hobby_anime.anilist_push.JellyfinClient", lambda *a, **k: fake_jellyfin
    )
    monkeypatch.setattr(
        "hobby_anime.anilist_push.AniListWriteClient", lambda *a, **k: fake_anilist
    )

    settings = Settings(
        database_path="db",  # type: ignore[arg-type]
        media_path="media",  # type: ignore[arg-type]
        rss_urls=(),
        rss_resolution="1080p",
        rss_groups=(),
        rss_include_terms=(),
        rss_exclude_terms=(),
        rss_max_age_hours=72,
        qbt_host="qbittorrent",
        qbt_port=8080,
        qbt_username="admin",
        qbt_password="secret",
        qbt_save_path="/data/torrents",
        qbt_category="hobby-anime",
        daily_hour=3,
        daily_minute=0,
        monthly_day=1,
        monthly_hour=9,
        timezone="UTC",
        anilist_url="https://graphql.anilist.co",
        ollama_enabled=False,
        ollama_url="http://ollama:11434",
        ollama_model="qwen2.5:3b",
        webhook_url="",
        telegram_bot_token="",
        telegram_chat_id="",
        jellyfin_url="http://jellyfin:8096",
        request_timeout_seconds=5,
    )
    database = FakeDatabase(token=VALID_TOKEN)

    report = run_push(settings, database, execute=False, sleep=_no_sleep)

    assert report.skipped_unchanged == 1
