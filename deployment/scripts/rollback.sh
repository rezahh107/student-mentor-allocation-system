#!/usr/bin/env bash
set -euo pipefail

# Example rollback: downgrade Alembic one revision
REVISION=${1:--1}
DATABASE_URL=${DATABASE_URL:-postgresql+psycopg2://alloc:alloc@localhost:5432/alloc}

alembic -x dburl="$DATABASE_URL" downgrade "$REVISION"
echo "Rolled back to $REVISION"
