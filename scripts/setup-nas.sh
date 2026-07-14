#!/usr/bin/env sh
set -eu

DATA_ROOT="${DATA_ROOT:-/volume1/data}"
CONFIG_ROOT="${CONFIG_ROOT:-/volume1/docker/hobby-anime}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Todas las rutas de datos viven bajo el mismo punto de montaje para permitir hardlinks.
mkdir -p \
    "$DATA_ROOT/torrents/quarantine" \
    "$DATA_ROOT/torrents/verified" \
    "$DATA_ROOT/media/anime" \
    "$CONFIG_ROOT/qbittorrent" \
    "$CONFIG_ROOT/jellyfin/config" \
    "$CONFIG_ROOT/jellyfin/cache" \
    "$CONFIG_ROOT/sonarr" \
    "$CONFIG_ROOT/prowlarr" \
    "$CONFIG_ROOT/bazarr" \
    "$CONFIG_ROOT/agent" \
    "$CONFIG_ROOT/ollama"

chown -R "$PUID:$PGID" "$DATA_ROOT" "$CONFIG_ROOT"
chmod 775 \
    "$DATA_ROOT" \
    "$DATA_ROOT/torrents" \
    "$DATA_ROOT/torrents/quarantine" \
    "$DATA_ROOT/torrents/verified" \
    "$DATA_ROOT/media" \
    "$DATA_ROOT/media/anime"

printf 'Directorios listos en %s y %s\n' "$DATA_ROOT" "$CONFIG_ROOT"
