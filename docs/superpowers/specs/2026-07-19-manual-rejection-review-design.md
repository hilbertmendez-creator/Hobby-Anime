# Manual Rejection Review — Design

Date: 2026-07-19
Status: Approved (design), pending implementation plan

## Problem

The verification pipeline is deliberately strict: `FfprobeInspector` rejects any
download whose Spanish audio/subtitle evidence is incomplete, partial, or
ambiguously tagged. As documented in the README, this correctly rejects some
content that is actually fine but was mislabeled by its publisher (false
negatives).

Today, recovering from a false negative requires manual intervention inside the
container: the rejected torrent is left stopped in `quarantine/` with category
`hobby-anime-rejected` and a row in `download_verification` (status `rejected`,
with the failing `reason`). There is no supported command to (a) see what was
rejected and why, or (b) override a rejection and promote it as if verified.

## Goal

Add a CLI-based manual review path with two commands:

1. `hobby-anime rejections` — list current rejections so the operator knows what
   exists and which torrent hash to act on.
2. `hobby-anime approve <hash> [<hash>...]` — force-promote one or more rejected
   downloads so they become indistinguishable from genuinely verified content.

Out of scope for this version (YAGNI): interactive Telegram bot control, bulk
approval by filter, `--dry-run` for approve, and approving `error`-state
downloads. Only `rejected` downloads can be approved.

## Current flow (grounding)

From `verification.py::run_verification` and `qbittorrent_client.py`:

- Rejected path: `gateway.reject(hash, rejected_category)` **stops** the torrent
  (`torrents_stop`) and sets category `hobby-anime-rejected`. The torrent is
  **not moved** — it stays in the quarantine `save_path`.
  `database.record_verification(download, "rejected", inspection)` persists the
  row with the failing reason.
- Accepted path: `gateway.accept(hash, verified_path, verified_category)` sets
  the location to `verified_path`, waits for the move to settle, then sets
  category `hobby-anime-verified`, and returns the promoted `TorrentDownload`.
  The torrent was never stopped, so it keeps seeding. If Sonarr is enabled with
  `sonarr_import_after_verify`, `database.queue_import(promoted)` enqueues it.
- `qbt_verify_categories` (default `("hobby-anime",)`) does **not** include the
  rejected or verified categories, so neither the auto-verifier nor a manual
  approve re-picks an already-categorized torrent.

Key consequence: a rejected torrent is **stopped**. Approving it must both
promote it (move + recategorize) **and resume seeding**, otherwise it ends up
promoted-but-paused.

## Design

### Command surface

`rejections`
- No arguments. Prints a human-readable table: short hash, name, reason, updated
  timestamp.
- `--json` flag emits the same data as JSON (consistent with `status`/`doctor`),
  for scripting.

`approve <hash> [<hash>...]`
- One or more torrent hashes as positional arguments.
- Each hash is processed **independently**; a failure on one hash logs and
  continues with the rest (same resilience pattern applied to `rss.fetch`).
- Exit code is non-zero if any requested approval failed.

### `approve` behavior, per hash

1. Look up the hash in `download_verification`. If it is missing or **not** in
   status `rejected`, report a clear error and **do not touch qBittorrent** for
   that hash.
2. **Do not re-inspect.** The entire purpose is to override a false negative;
   re-running ffprobe would just re-reject it.
3. Call `gateway.accept(hash, verified_path, verified_category, resume=True)`:
   move to `verified/`, set category `hobby-anime-verified`, and **resume** the
   torrent (it was stopped by the earlier reject).
4. Only after qBittorrent succeeds, record the verification as `verified` with an
   audit trail in the reason:
   `"Manually approved (was rejected: <original reason>)"`. This keeps the
   override human-traceable while making the row otherwise identical to a genuine
   verification.
5. If `sonarr_enabled` and `sonarr_import_after_verify`, enqueue the import via
   `database.queue_import(promoted)` — identical to the automatic accepted path.
6. **Ordering guarantees consistency:** qBittorrent side first, DB flip second.
   If `gateway.accept` fails partway, the row stays `rejected` — no
   verified-but-not-actually-promoted inconsistency.

### Component changes

| File | Change |
| --- | --- |
| `manual_review.py` (new) | `list_rejections(settings, *, database=None)` and `approve_rejection(settings, torrent_hash, *, gateway=None, database=None)`. Pure logic, dependency-injected like the other command modules (`daily.py`, `verification.py`, `library_import.py`). No notification is sent on manual approve — the operator sees the CLI result directly (YAGNI). |
| `database.py` | `rejected_downloads(torrent_hash: str | None = None) -> list[RejectedDownload]`. Queries `download_verification WHERE status = 'rejected'`, optionally filtered by hash for the single-hash validation in approve. |
| `models.py` | New `RejectedDownload` dataclass: `torrent_hash`, `name`, `reason`, `content_path`, `updated_at`. Avoids passing raw `sqlite3.Row` across module boundaries. |
| `qbittorrent_client.py` | Add `resume: bool = False` param to `accept()`. When true, call `torrents_start(torrent_hashes=hash)` after the category is set. Automatic path keeps default `False`, so its behavior is unchanged. |
| `cli.py` | Wire the `rejections` and `approve` subcommands: argument parsing, table/JSON output, exit-code mapping. |

### Error handling

- Unknown or non-`rejected` hash: clear message, non-zero exit, no qBittorrent
  call for that hash.
- qBittorrent unreachable / torrent no longer present: the `gateway.accept`
  exception is caught per hash; the DB row is left as `rejected`; the error is
  reported and contributes to a non-zero exit code.
- Multi-hash: independent per-hash processing; one failure never aborts the rest.

### Testing

- `test_manual_review.py` (new):
  - Approving a `rejected` hash promotes it, resumes it, records `verified` with
    the audit-trail reason, and enqueues a Sonarr import when Sonarr is enabled.
  - Approving an unknown or non-`rejected` hash raises/reports an error and never
    calls the gateway.
  - A gateway failure leaves the row as `rejected` (no partial state).
  - Multi-hash where one fails still processes the others.
- `test_database.py`: extend for `rejected_downloads()` (all + filtered-by-hash).
- `test_qbittorrent_client.py`: `accept(resume=True)` calls `torrents_start`;
  `accept()` (default) does not.
- `test_cli.py` (new): the `rejections` and `approve` commands, including
  exit-code behavior. This also begins closing the `cli.py` zero-coverage gap
  the audit flagged.

## Non-goals / deferred

- Interactive Telegram approval (requires an inbound control channel — separate
  design with its own auth model).
- Bulk approval by filter/glob.
- `--dry-run` on approve (the `rejections` command already provides preview).
- Approving `error`-state downloads (would promote never-inspected content).
