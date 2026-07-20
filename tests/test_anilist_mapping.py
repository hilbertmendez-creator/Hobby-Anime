from hobby_anime.anilist_mapping import (
    build_report,
    decide_target,
    needs_push,
    normalize_match_title,
    resolve_media_id,
)
from hobby_anime.models import AniListMatch, AniListPushCandidate, WatchedSeries

# --- normalize_match_title (task 4.1) ---


def test_normalize_match_title_is_case_and_punctuation_insensitive() -> None:
    assert normalize_match_title("Attack on Titan!") == normalize_match_title("ATTACK ON TITAN")


def test_normalize_match_title_ignores_whitespace_variance() -> None:
    assert normalize_match_title("Attack  on   Titan") == normalize_match_title("Attack on Titan")


def test_normalize_match_title_strips_season_marker() -> None:
    assert normalize_match_title("Attack on Titan Season 2") == normalize_match_title("Attack on Titan")


def test_normalize_match_title_strips_part_marker() -> None:
    assert normalize_match_title("Attack on Titan Part 2") == normalize_match_title("Attack on Titan")


def test_normalize_match_title_strips_short_season_marker() -> None:
    assert normalize_match_title("Attack on Titan S2") == normalize_match_title("Attack on Titan")


def test_normalize_match_title_is_deterministic() -> None:
    assert normalize_match_title("Frieren: Beyond Journey's End") == normalize_match_title(
        "Frieren: Beyond Journey's End"
    )


# --- resolve_media_id: override always wins (task 4.2) ---


def _series(name: str = "Frieren", watched: int = 12, total: int = 12) -> WatchedSeries:
    return WatchedSeries(id="s1", name=name, total_episodes=total, watched_episodes=watched)


def test_resolve_media_id_override_wins_over_auto_match() -> None:
    series = _series("Frieren")
    override = {"override_media_id": 999, "auto_media_id": None}
    matches = [AniListMatch(media_id=1, title="Frieren", year=2023)]

    media_id, source, reason = resolve_media_id(series, override, matches)

    assert (media_id, source, reason) == (999, "override", "")


def test_resolve_media_id_override_rescues_unmatchable_series() -> None:
    series = _series("Some Untitled Series")
    override = {"override_media_id": 555, "auto_media_id": None}
    matches: list[AniListMatch] = []

    media_id, source, reason = resolve_media_id(series, override, matches)

    assert (media_id, source, reason) == (555, "override", "")


# --- resolve_media_id: single exact auto-match accepted (task 4.3) ---


def test_resolve_media_id_single_normalized_match_is_auto() -> None:
    series = _series("Frieren")
    matches = [AniListMatch(media_id=42, title="Frieren", year=2023)]

    media_id, source, reason = resolve_media_id(series, None, matches)

    assert (media_id, source, reason) == (42, "auto", "")


def test_resolve_media_id_ignores_case_and_punctuation_for_auto_match() -> None:
    series = _series("Attack on Titan!")
    matches = [AniListMatch(media_id=7, title="attack on titan")]

    media_id, source, reason = resolve_media_id(series, None, matches)

    assert (media_id, source, reason) == (7, "auto", "")


# --- resolve_media_id: multiple candidates -> skip (task 4.4) ---


def test_resolve_media_id_multiple_candidates_skip_unmapped() -> None:
    series = _series("Frieren")
    matches = [
        AniListMatch(media_id=1, title="Frieren", year=2023),
        AniListMatch(media_id=2, title="Frieren", year=2024),
    ]

    media_id, source, reason = resolve_media_id(series, None, matches)

    assert (media_id, source, reason) == (None, "", "unmapped")


# --- resolve_media_id: zero candidates -> skip (task 4.4) ---


def test_resolve_media_id_zero_candidates_skip_unmapped() -> None:
    series = _series("A Totally Unknown Show")
    matches = [AniListMatch(media_id=1, title="Something Else")]

    media_id, source, reason = resolve_media_id(series, None, matches)

    assert (media_id, source, reason) == (None, "", "unmapped")


def test_resolve_media_id_no_override_no_matches_skip_unmapped() -> None:
    series = _series("A Totally Unknown Show")

    media_id, source, reason = resolve_media_id(series, None, [])

    assert (media_id, source, reason) == (None, "", "unmapped")


# --- resolve_media_id: year disagreement -> skip (task 4.4) ---


def test_resolve_media_id_year_disagreement_skips() -> None:
    series = _series("Frieren")
    matches = [AniListMatch(media_id=1, title="Frieren", year=2019)]

    media_id, source, reason = resolve_media_id(series, None, matches, series_year=2023)

    assert (media_id, source, reason) == (None, "", "unmapped")


def test_resolve_media_id_year_agreement_still_matches() -> None:
    series = _series("Frieren")
    matches = [AniListMatch(media_id=1, title="Frieren", year=2023)]

    media_id, source, reason = resolve_media_id(series, None, matches, series_year=2023)

    assert (media_id, source, reason) == (1, "auto", "")


def test_resolve_media_id_year_disambiguates_multiple_title_matches() -> None:
    series = _series("Frieren")
    matches = [
        AniListMatch(media_id=1, title="Frieren", year=2019),
        AniListMatch(media_id=2, title="Frieren", year=2023),
    ]

    media_id, source, reason = resolve_media_id(series, None, matches, series_year=2023)

    assert (media_id, source, reason) == (2, "auto", "")


def test_resolve_media_id_override_dict_without_override_key_falls_back_to_auto() -> None:
    series = _series("Frieren")
    override = {"override_media_id": None, "auto_media_id": 42}
    matches = [AniListMatch(media_id=42, title="Frieren", year=2023)]

    media_id, source, reason = resolve_media_id(series, override, matches)

    assert (media_id, source, reason) == (42, "auto", "")


# --- decide_target (task 4.5) ---


def test_decide_target_complete_series_is_completed_with_total() -> None:
    series = _series(watched=12, total=12)

    assert decide_target(series, progress_mode=False) == ("COMPLETED", 12)


def test_decide_target_complete_series_with_progress_mode_is_completed_with_total() -> None:
    series = _series(watched=12, total=12)

    assert decide_target(series, progress_mode=True) == ("COMPLETED", 12)


def test_decide_target_partial_series_with_progress_mode_is_current_with_watched() -> None:
    series = _series(watched=5, total=12)

    assert decide_target(series, progress_mode=True) == ("CURRENT", 5)


# --- needs_push: idempotency (task 4.6) ---


def test_needs_push_true_when_no_current_entry() -> None:
    assert needs_push("COMPLETED", 12, None) is True


def test_needs_push_false_when_entry_already_matches() -> None:
    assert needs_push("COMPLETED", 12, ("COMPLETED", 12)) is False


def test_needs_push_true_when_status_differs() -> None:
    assert needs_push("COMPLETED", 12, ("CURRENT", 12)) is True


def test_needs_push_true_when_progress_differs() -> None:
    assert needs_push("CURRENT", 6, ("CURRENT", 5)) is True


def test_needs_push_false_when_current_progress_is_higher_never_decrease() -> None:
    assert needs_push("CURRENT", 3, ("CURRENT", 8)) is False


def test_needs_push_false_when_current_progress_higher_even_if_status_differs() -> None:
    assert needs_push("CURRENT", 3, ("COMPLETED", 12)) is False


# --- build_report (task 4.7) ---


def test_build_report_aggregates_pushed_and_skips() -> None:
    candidates = (
        AniListPushCandidate(
            series_id="s1", series_name="A", media_id=1, source="auto", status="COMPLETED", progress=12
        ),
        AniListPushCandidate(
            series_id="s2",
            series_name="B",
            media_id=None,
            source="",
            status="",
            progress=0,
            skip_reason="unmapped",
        ),
        AniListPushCandidate(
            series_id="s3",
            series_name="C",
            media_id=2,
            source="auto",
            status="COMPLETED",
            progress=12,
            skip_reason="unchanged",
        ),
        AniListPushCandidate(
            series_id="s4",
            series_name="D",
            media_id=3,
            source="override",
            status="CURRENT",
            progress=5,
            skip_reason="failed",
        ),
    )

    report = build_report(candidates)

    assert report.pushed == 1
    assert report.skipped_unmapped == 1
    assert report.skipped_unchanged == 1
    assert report.failed == 1
    assert report.candidates == candidates


def test_build_report_empty_candidates() -> None:
    report = build_report(())

    assert report.pushed == 0
    assert report.skipped_unmapped == 0
    assert report.skipped_unchanged == 0
    assert report.failed == 0
    assert report.candidates == ()
