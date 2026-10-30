#!/usr/bin/env bash
# Usage: ./scripts/backup.sh   (run from the project directory; schedule with cron, see README)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
DIR="${BACKUP_HOST_DIR:-./backups}"; KEEP="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$DIR"; chmod 700 "$DIR"
FILE="$DIR/shopbot_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$FILE"
chmod 600 "$FILE"
[ -s "$FILE" ] || { echo "Backup is empty, removing"; rm -f "$FILE"; exit 1; }
find "$DIR" -name 'shopbot_*.dump' -mtime +"$KEEP" -delete
echo "Backup written: $FILE"
