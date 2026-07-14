from pathlib import Path

from hobby_anime.database import TrackingDatabase
from hobby_anime.models import FeedItem


def test_tracking_database_retries_errors_and_skips_added(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "nested" / "tracking.db")
    item = FeedItem("fingerprint", "Example", "magnet:?xt=example")
    database.initialize()

    database.record_error(item, "temporary failure")
    assert database.was_added(item.fingerprint) is False

    database.record_added(item)
    assert database.was_added(item.fingerprint) is True
