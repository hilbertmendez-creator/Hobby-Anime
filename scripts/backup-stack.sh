#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

CONFIG_ROOT="${CONFIG_ROOT:-/volume1/docker/hobby-anime}"
BACKUP_ROOT="${BACKUP_ROOT:-/volume1/backups/hobby-anime}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DESTINATION="$BACKUP_ROOT/$TIMESTAMP"
SERVICES=(hobby-anime sonarr prowlarr bazarr qbittorrent jellyfin)
STOPPED=0

restart_services() {
    if [[ "$STOPPED" -eq 1 ]]; then
        docker compose start "${SERVICES[@]}"
    fi
}
trap restart_services EXIT

# Se detienen las bases SQLite para obtener una copia consistente.
docker compose stop "${SERVICES[@]}"
STOPPED=1

install -d -m 700 "$DESTINATION"
tar -C "$CONFIG_ROOT" -czf "$DESTINATION/config.tar.gz" .
chmod 600 "$DESTINATION/config.tar.gz"

if [[ -f .env ]]; then
    install -m 600 .env "$DESTINATION/environment.env"
fi

{
    printf 'created_at=%s\n' "$TIMESTAMP"
    printf 'git_revision=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unknown)"
    printf 'config_root=%s\n' "$CONFIG_ROOT"
} >"$DESTINATION/manifest.txt"
chmod 600 "$DESTINATION/manifest.txt"

printf 'Backup created at %s\n' "$DESTINATION"
