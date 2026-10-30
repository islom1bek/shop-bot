#!/usr/bin/env bash
# Usage: ./scripts/restore.sh backups/shopbot_YYYYMMDD_HHMMSS.dump   (REPLACES the current data!)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
FILE="${1:?backup file required}"
read -r -p "This will overwrite the database '$POSTGRES_DB'. Type YES to continue: " ans
[ "$ans" = "YES" ] || exit 1
docker compose stop bot
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner < "$FILE"
docker compose start bot
echo "Restore finished."
