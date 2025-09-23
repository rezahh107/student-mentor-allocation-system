#!/usr/bin/env bash
set -euo pipefail

PG_HOST=${PG_HOST:-localhost}
PG_PORT=${PG_PORT:-5432}
PG_USER=${PG_USER:-alloc}
PG_DB=${PG_DB:-alloc}
IN=${1:-backup.sql.gz}

gunzip -c "$IN" | psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB"
echo "Restore completed from $IN"
