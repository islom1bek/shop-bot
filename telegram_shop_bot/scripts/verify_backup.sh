#!/usr/bin/env bash
# Restores a backup into a throw-away database and counts tables, proving the file is usable.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
FILE="${1:?backup file required}"
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS verify_tmp" -c "CREATE DATABASE verify_tmp"
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d verify_tmp --no-owner < "$FILE"
docker compose exec -T db psql -U "$POSTGRES_USER" -d verify_tmp -tc "SELECT count(*) || ' tables restored' FROM information_schema.tables WHERE table_schema='public'"
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE verify_tmp"
