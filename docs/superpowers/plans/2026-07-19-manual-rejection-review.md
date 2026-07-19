# Manual Rejection Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two CLI commands — `hobby-anime rejections` (list) and `hobby-anime approve <hash>...` (force-promote) — so an operator can override false-negative language rejections without touching the container internals.

**Architecture:** A new dependency-injected `manual_review.py` module holds the pure logic (mirroring `daily.py`/`verification.py`/`library_import.py`). It reads rejected rows from `download_verification` via a new `TrackingDatabase.rejected_downloads()` query, and promotes via the existing `QBittorrentGateway.accept()` — extended with a `resume=True` flag because `reject()` leaves the torrent stopped. The qBittorrent move happens before the DB status flip, so a gateway failure leaves the row `rejected`.

**Tech Stack:** Python 3.11+, argparse, sqlite3, `qbittorrent-api`, pytest.

**Commit convention:** Conventional Commits (`feat:`, `test:`), no `Co-Authored-By` trailer. The project owner commits only when they choose to — commit steps are included per TDD workflow, but confirm with the owner before pushing.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/hobby_anime/models.py` | Add `RejectedDownload` dataclass (read model for a rejected row) |
| `src/hobby_anime/database.py` | Add `rejected_downloads(hash=None)` query |
| `src/hobby_anime/qbittorrent_client.py` | Add `resume` flag to `accept()` |
| `src/hobby_anime/manual_review.py` (new) | `list_rejections()`, `approve_rejection()`, `ApprovalError` |
| `src/hobby_anime/cli.py` | Wire `rejections` and `approve` subcommands |
| `tests/test_database.py` | Cover `rejected_downloads()` |
| `tests/test_qbittorrent_client.py` | Cover `accept(resume=True)` |
| `tests/test_manual_review.py` (new) | Cover list + approve logic and failure paths |
| `tests/test_cli.py` (new) | Cover parser + command dispatch/exit codes |

Run all tests with the project venv: `.venv/Scripts/python -m pytest` (Windows dev) — on the deployment target it's `pytest`.

---

## Task 1: `RejectedDownload` model + `rejected_downloads()` query

**Files:**
- Modify: `src/hobby_anime/models.py`
- Modify: `src/hobby_anime/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_database.py` (it already imports `Path`, `TrackingDatabase`, `FeedItem`, `TorrentDownload`):

```python
def test_rejected_downloads_lists_only_rejected(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    database.record_verification(
        TorrentDownload("hash-ok", "Verified show", Path("/data/torrents/verified/ok.mkv")),
        "verified",
        reason="Spanish subtitles verified",
    )
    database.record_verification(
        TorrentDownload("hash-bad", "Rejected show", Path("/data/torrents/quarantine/bad.mkv")),
        "rejected",
        reason="No Spanish tracks",
    )

    downloads = database.rejected_downloads()

    assert [d.torrent_hash for d in downloads] == ["hash-bad"]
    assert downloads[0].name == "Rejected show"
    assert downloads[0].reason == "No Spanish tracks"
    assert downloads[0].content_path == Path("/data/torrents/quarantine/bad.mkv")


def test_rejected_downloads_filters_by_hash(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    for index in range(2):
        database.record_verification(
            TorrentDownload(f"hash-{index}", f"Show {index}", Path(f"/q/{index}.mkv")),
            "rejected",
            reason=f"reason {index}",
        )

    downloads = database.rejected_downloads("hash-1")

    assert len(downloads) == 1
    assert downloads[0].torrent_hash == "hash-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_database.py::test_rejected_downloads_lists_only_rejected tests/test_database.py::test_rejected_downloads_filters_by_hash -v`
Expected: FAIL — `AttributeError: 'TrackingDatabase' object has no attribute 'rejected_downloads'`.

- [ ] **Step 3: Add the `RejectedDownload` model**

In `src/hobby_anime/models.py`, after the `TorrentDownload` dataclass (ends line 22), add:

```python
@dataclass(frozen=True)
class RejectedDownload:
    torrent_hash: str
    name: str
    reason: str
    content_path: Path
    updated_at: str
```

- [ ] **Step 4: Add the query**

In `src/hobby_anime/database.py`, extend the models import on line 12:

```python
from hobby_anime.models import FeedItem, MediaInspection, RejectedDownload, TorrentDownload
```

Then add this method to `TrackingDatabase` (place it after `verification_status`, before `claim_verification`):

```python
def rejected_downloads(
    self,
    torrent_hash: str | None = None,
) -> list[RejectedDownload]:
    query = (
        "SELECT torrent_hash, name, reason, content_path, updated_at "
        "FROM download_verification WHERE status = 'rejected'"
    )
    params: tuple[str, ...] = ()
    if torrent_hash is not None:
        query += " AND torrent_hash = ?"
        params = (torrent_hash,)
    query += " ORDER BY updated_at DESC"
    with self.connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        RejectedDownload(
            torrent_hash=str(row["torrent_hash"]),
            name=str(row["name"]),
            reason=str(row["reason"] or ""),
            content_path=Path(str(row["content_path"])),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_database.py -v`
Expected: PASS (including the two new tests).

- [ ] **Step 6: Commit**

```bash
git add src/hobby_anime/models.py src/hobby_anime/database.py tests/test_database.py
git commit -m "feat: add rejected_downloads query and RejectedDownload model"
```

---

## Task 2: `accept(resume=...)` on the qBittorrent gateway

**Files:**
- Modify: `src/hobby_anime/qbittorrent_client.py:66-83`
- Test: `tests/test_qbittorrent_client.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_qbittorrent_client.py`, add a `started` list and a `torrents_start` method to `FakeClient`. Change the `__init__` body (after line 18 `self.current_save_path = ...`) to also set:

```python
        self.started: list[str] = []
```

And add this method to `FakeClient` (after `torrents_stop`, line 52):

```python
    def torrents_start(self, torrent_hashes: str) -> None:
        self.started.append(torrent_hashes)
```

Then add these two tests at the end of the file:

```python
def test_accept_resumes_torrent_when_requested() -> None:
    client = FakeClient()
    gateway = QBittorrentGateway(
        "host", 8080, "user", "pass",
        "/data/torrents/quarantine", "anime", client,
    )

    gateway.accept("abc123", "/data/torrents/verified", "anime-verified", resume=True)

    assert client.started == ["abc123"]


def test_accept_does_not_resume_by_default() -> None:
    client = FakeClient()
    gateway = QBittorrentGateway(
        "host", 8080, "user", "pass",
        "/data/torrents/quarantine", "anime", client,
    )

    gateway.accept("abc123", "/data/torrents/verified", "anime-verified")

    assert client.started == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_qbittorrent_client.py::test_accept_resumes_torrent_when_requested -v`
Expected: FAIL — `TypeError: accept() got an unexpected keyword argument 'resume'`.

- [ ] **Step 3: Add the `resume` flag**

In `src/hobby_anime/qbittorrent_client.py`, replace the `accept` method (lines 66-83) with:

```python
    def accept(
        self,
        torrent_hash: str,
        verified_path: str,
        verified_category: str,
        resume: bool = False,
    ) -> TorrentDownload:
        self.client.auth_log_in()
        self._ensure_category(verified_category, verified_path)
        self.client.torrents_set_location(
            location=verified_path,
            torrent_hashes=torrent_hash,
        )
        promoted = self._wait_for_location(torrent_hash, verified_path)
        self.client.torrents_set_category(
            category=verified_category,
            torrent_hashes=torrent_hash,
        )
        if resume:
            self.client.torrents_start(torrent_hashes=torrent_hash)
        return promoted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_qbittorrent_client.py -v`
Expected: PASS (new tests pass, existing `accept` test unaffected — it never inspects `started`).

- [ ] **Step 5: Commit**

```bash
git add src/hobby_anime/qbittorrent_client.py tests/test_qbittorrent_client.py
git commit -m "feat: add resume flag to QBittorrentGateway.accept"
```

---

## Task 3: `manual_review.py` — list + approve logic

**Files:**
- Create: `src/hobby_anime/manual_review.py`
- Test: `tests/test_manual_review.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manual_review.py`:

```python
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.manual_review import ApprovalError, approve_rejection, list_rejections
from hobby_anime.models import TorrentDownload


class FakeGateway:
    def __init__(self) -> None:
        self.accepted: list[tuple[str, str, str, bool]] = []

    def accept(
        self,
        torrent_hash: str,
        verified_path: str,
        verified_category: str,
        resume: bool = False,
    ) -> TorrentDownload:
        self.accepted.append((torrent_hash, verified_path, verified_category, resume))
        return TorrentDownload(
            torrent_hash,
            "Rejected show",
            Path(verified_path) / "bad.mkv",
        )


class FailingGateway:
    def accept(self, *args: object, **kwargs: object) -> TorrentDownload:
        raise RuntimeError("qBittorrent unreachable")


def _seed_rejected(database: TrackingDatabase, tmp_path: Path) -> None:
    database.initialize()
    database.record_verification(
        TorrentDownload("hash-bad", "Rejected show", tmp_path / "bad.mkv"),
        "rejected",
        reason="No Spanish tracks",
    )


def test_list_rejections_returns_only_rejected(settings: Settings, tmp_path: Path) -> None:
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)
    database.record_verification(
        TorrentDownload("hash-ok", "Verified", tmp_path / "ok.mkv"),
        "verified",
        reason="Spanish subtitles verified",
    )

    result = list_rejections(settings, database=database)

    assert [r.torrent_hash for r in result] == ["hash-bad"]


def test_approve_promotes_resumes_and_records_audit(settings: Settings, tmp_path: Path) -> None:
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)
    gateway = FakeGateway()

    result = approve_rejection(settings, "hash-bad", gateway=gateway, database=database)

    assert gateway.accepted == [
        ("hash-bad", settings.qbt_verified_path, settings.qbt_verified_category, True)
    ]
    assert database.verification_status("hash-bad") == "verified"
    assert database.rejected_downloads() == []
    assert result.name == "Rejected show"
    with sqlite3.connect(database.path) as connection:
        reason = connection.execute(
            "SELECT reason FROM download_verification WHERE torrent_hash = 'hash-bad'"
        ).fetchone()[0]
    assert reason == "Manually approved (was rejected: No Spanish tracks)"


def test_approve_unknown_hash_raises_without_touching_gateway(settings: Settings) -> None:
    database = TrackingDatabase(settings.database_path)
    database.initialize()
    gateway = FakeGateway()

    with pytest.raises(ApprovalError):
        approve_rejection(settings, "nope", gateway=gateway, database=database)

    assert gateway.accepted == []


def test_approve_gateway_failure_leaves_row_rejected(settings: Settings, tmp_path: Path) -> None:
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)

    with pytest.raises(RuntimeError):
        approve_rejection(settings, "hash-bad", gateway=FailingGateway(), database=database)

    assert database.verification_status("hash-bad") == "rejected"


def test_approve_queues_sonarr_import_when_enabled(settings: Settings, tmp_path: Path) -> None:
    settings = replace(
        settings,
        sonarr_enabled=True,
        sonarr_import_after_verify=True,
        sonarr_api_key="key",
    )
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)

    approve_rejection(settings, "hash-bad", gateway=FakeGateway(), database=database)

    assert [d.torrent_hash for d in database.pending_imports()] == ["hash-bad"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_manual_review.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hobby_anime.manual_review'`.

- [ ] **Step 3: Create the module**

Create `src/hobby_anime/manual_review.py`:

```python
from __future__ import annotations

import logging

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import RejectedDownload
from hobby_anime.qbittorrent_client import QBittorrentGateway

LOGGER = logging.getLogger(__name__)


class ApprovalError(ValueError):
    """Raised when a hash cannot be approved (unknown or not in 'rejected')."""


def _database(settings: Settings, database: TrackingDatabase | None) -> TrackingDatabase:
    database = database or TrackingDatabase(settings.database_path)
    database.initialize()
    return database


def list_rejections(
    settings: Settings,
    *,
    database: TrackingDatabase | None = None,
) -> list[RejectedDownload]:
    return _database(settings, database).rejected_downloads()


def approve_rejection(
    settings: Settings,
    torrent_hash: str,
    *,
    gateway: QBittorrentGateway | None = None,
    database: TrackingDatabase | None = None,
) -> RejectedDownload:
    if not settings.qbt_password:
        raise ValueError("QBITTORRENT_PASSWORD is required")

    database = _database(settings, database)
    matches = database.rejected_downloads(torrent_hash)
    if not matches:
        raise ApprovalError(f"{torrent_hash} is not a rejected download")
    rejected = matches[0]

    gateway = gateway or QBittorrentGateway(
        settings.qbt_host,
        settings.qbt_port,
        settings.qbt_username,
        settings.qbt_password,
        settings.qbt_save_path,
        settings.qbt_category,
        move_timeout_seconds=settings.qbt_move_timeout_seconds,
    )
    promoted = gateway.accept(
        torrent_hash,
        settings.qbt_verified_path,
        settings.qbt_verified_category,
        resume=True,
    )
    database.record_verification(
        promoted,
        "verified",
        reason=f"Manually approved (was rejected: {rejected.reason})",
    )
    if settings.sonarr_enabled and settings.sonarr_import_after_verify:
        database.queue_import(promoted)
    LOGGER.info("Manually approved rejected download: %s", rejected.name)
    return rejected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_manual_review.py -v`
Expected: PASS (all six tests).

- [ ] **Step 5: Commit**

```bash
git add src/hobby_anime/manual_review.py tests/test_manual_review.py
git commit -m "feat: add manual rejection review logic"
```

---

## Task 4: Wire `rejections` and `approve` CLI commands

**Files:**
- Modify: `src/hobby_anime/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
import sys
from types import SimpleNamespace

import hobby_anime.cli as cli
from hobby_anime.config import Settings
from hobby_anime.models import RejectedDownload
from pathlib import Path


def test_parser_parses_approve_hashes() -> None:
    args = cli.build_parser().parse_args(["approve", "h1", "h2"])
    assert args.command == "approve"
    assert args.hashes == ["h1", "h2"]


def test_parser_rejections_json_flag() -> None:
    args = cli.build_parser().parse_args(["rejections", "--json"])
    assert args.command == "rejections"
    assert args.json is True


def test_approve_command_returns_nonzero_when_a_hash_fails(
    monkeypatch, settings: Settings
) -> None:
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    calls: list[str] = []

    def fake_approve(_settings: Settings, torrent_hash: str, **_kwargs: object):
        calls.append(torrent_hash)
        if torrent_hash == "bad":
            raise cli.ApprovalError("not a rejected download")
        return SimpleNamespace(name="ok")

    monkeypatch.setattr(cli, "approve_rejection", fake_approve)
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "approve", "good", "bad"])

    assert cli.main() == 1
    assert calls == ["good", "bad"]


def test_rejections_command_prints_and_returns_zero(
    monkeypatch, settings: Settings, capsys
) -> None:
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(
        cli,
        "list_rejections",
        lambda _settings: [
            RejectedDownload("hash-bad", "Rejected show", "No Spanish tracks", Path("/q/bad.mkv"), "2026-07-19T00:00:00")
        ],
    )
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "rejections"])

    assert cli.main() == 0
    assert "hash-bad" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `AttributeError: module 'hobby_anime.cli' has no attribute 'approve_rejection'` (and the parser tests fail on unknown `approve`/`rejections` commands).

- [ ] **Step 3: Wire the commands**

In `src/hobby_anime/cli.py`, add to the imports (after line 15, `from hobby_anime.monthly import run_monthly`):

```python
from hobby_anime.manual_review import ApprovalError, approve_rejection, list_rejections
```

In `build_parser()`, add the two subparsers just before `return parser` (after line 33):

```python
    rejections_parser = subparsers.add_parser(
        "rejections", help="List downloads rejected by the language policy"
    )
    rejections_parser.add_argument(
        "--json", action="store_true", help="Emit the rejection list as JSON"
    )
    approve_parser = subparsers.add_parser(
        "approve", help="Force-promote one or more rejected downloads"
    )
    approve_parser.add_argument(
        "hashes", nargs="+", help="Torrent hashes to approve"
    )
```

In `main()`, add these two branches before the final `return 2` (after line 87):

```python
    if args.command == "rejections":
        rejections = list_rejections(settings)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "torrent_hash": rejected.torrent_hash,
                            "name": rejected.name,
                            "reason": rejected.reason,
                            "content_path": str(rejected.content_path),
                            "updated_at": rejected.updated_at,
                        }
                        for rejected in rejections
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for rejected in rejections:
                print(
                    f"{rejected.torrent_hash[:12]}  {rejected.name}  "
                    f"({rejected.reason})"
                )
        return 0
    if args.command == "approve":
        failures = 0
        for torrent_hash in args.hashes:
            try:
                rejected = approve_rejection(settings, torrent_hash)
                print(f"approved {torrent_hash}: {rejected.name}")
            except Exception as exc:  # per-hash resilience: one failure never aborts the rest
                failures += 1
                print(f"failed {torrent_hash}: {exc}")
        return 1 if failures else 0
```

Note: the `ApprovalError` import is used by the test suite (`cli.ApprovalError`) and documents the specific failure type; the broad `except Exception` is intentional so a gateway/network error on one hash still lets the others proceed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python -m pytest`
Expected: all tests pass (1 skipped: the Windows symlink test).

- [ ] **Step 6: Commit**

```bash
git add src/hobby_anime/cli.py tests/test_cli.py
git commit -m "feat: add rejections and approve CLI commands"
```

---

## Task 5: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the commands**

In `README.md`, in the `## Comandos` code block (around line 254-265), add the two new commands after `hobby-anime status`:

```bash
hobby-anime rejections
hobby-anime approve <hash>
```

Then add a short paragraph after that block explaining: `rejections` lists downloads the language policy rejected (hash, name, reason); `approve <hash>` force-promotes a rejected download — it moves the torrent to `verified/`, resumes seeding, records it as verified with an audit note, and (if Sonarr is enabled) queues the import. Note that approve does not re-inspect, so use it only for downloads you have confirmed are correctly labeled.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document rejections and approve commands"
```

---

## Self-Review Notes

- **Spec coverage:** `rejections` + `--json` (Task 4) ✓; `approve` multi-hash independent processing (Task 4) ✓; only `rejected` state approvable (`rejected_downloads` filter + `ApprovalError`, Tasks 1/3) ✓; no re-inspect (Task 3 — approve never calls the inspector) ✓; resume seeding (Task 2 + Task 3 `resume=True`) ✓; audit-trail reason (Task 3) ✓; Sonarr import mirrors auto path (Task 3) ✓; qBittorrent-first-then-DB ordering (Task 3 — `accept` before `record_verification`) ✓; no notification on approve (module has no `Notifier`) ✓; `cli.py` coverage gap started (Task 4) ✓.
- **Type consistency:** `RejectedDownload(torrent_hash, name, reason, content_path, updated_at)` used identically in models, database, manual_review, and cli. `accept(torrent_hash, verified_path, verified_category, resume=False)` signature matches across gateway, fakes, and calls.
- **No placeholders:** every code step contains complete, runnable code.
