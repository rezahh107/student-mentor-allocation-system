#!/usr/bin/env bash
set -euo pipefail

PG_HOST=${PG_HOST:-localhost}
PG_PORT=${PG_PORT:-5432}
PG_USER=${PG_USER:-alloc}
PG_DB=${PG_DB:-alloc}
OUT=${1:-backup_$(date +%Y%m%d_%H%M).sql.gz}

pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" | gzip > "$OUT"
echo "Backup written to $OUT"
