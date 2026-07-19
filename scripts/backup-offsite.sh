#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

BACKUP_ROOT="${BACKUP_ROOT:-/volume1/backups/hobby-anime}"
OFFSITE_RCLONE_REMOTE="${OFFSITE_RCLONE_REMOTE:-}"

# Puerta de activación: sin remoto configurado, no se hace nada (no-op seguro).
if [[ -z "$OFFSITE_RCLONE_REMOTE" ]]; then
    printf 'Backup remoto desactivado (OFFSITE_RCLONE_REMOTE vacío); no se ejecuta rclone.\n'
    exit 0
fi

# Se selecciona el snapshot más reciente por fecha de modificación.
latest="$(ls -dt "$BACKUP_ROOT"/*/ 2>/dev/null | head -1 || true)"

if [[ -z "$latest" || ! -d "$latest" ]]; then
    printf 'Error: no se encontró ningún snapshot en %s\n' "$BACKUP_ROOT" >&2
    exit 1
fi

snapshot="$(basename "$latest")"
destination="$OFFSITE_RCLONE_REMOTE/$snapshot"

# Copia aditiva: nunca se usa "rclone sync" para no borrar snapshots remotos existentes.
if ! rclone copy "$latest" "$destination"; then
    printf 'Error: rclone copy falló (origen=%s destino=%s)\n' "$latest" "$destination" >&2
    exit 1
fi

printf 'Snapshot %s subido correctamente a %s\n' "$snapshot" "$destination"
