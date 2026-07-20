## v0.1.0 (2026-07-20)

### Feat

- **anilist**: add watched-progress push (Item C) (#16)
- **cli**: add cleanup command with dry-run-default safety flags
- **cleanup**: add dry-run-default disk cleanup engine
- **cleanup**: resolve watched series on-disk path and add cleanup models
- **cli**: add watched command for Jellyfin status
- **backup**: add opt-in rclone offsite backup script
- **jellyfin**: add read-only watched-status client
- **api**: add token-guarded FastAPI status and health endpoints
- cap agent and ollama resource usage on the NAS
- add healthcheck to hobby-anime service
- add rejections and approve CLI commands
- add manual rejection review logic
- add resume flag to QBittorrentGateway.accept
- add rejected_downloads query and RejectedDownload model
- deploy hybrid arr media stack
- integrate verified downloads with Sonarr
- enforce Spanish media verification

### Fix

- **backup**: set STOPPED flag before docker compose stop
- detect qBittorrent error state during promotion
- keep monthly report resilient to AniList and Sonarr failures
- enforce daily language-policy validation
- derive claim staleness from configured timeouts
- validate RSS URL schemes and isolate per-feed failures
- prevent Bazarr API key leak via X-Api-Key header
- harden quarantine verification workflow
- validate external Spanish subtitle content
