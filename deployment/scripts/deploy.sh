#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT=${1:-dev}
BASE_DIR=$(cd "$(dirname "$0")" && pwd)

case "$ENVIRONMENT" in
  dev) COMPOSE_FILE="$BASE_DIR/../docker/docker-compose.dev.yml" ;;
  staging) COMPOSE_FILE="$BASE_DIR/../docker/docker-compose.staging.yml" ;;
  prod) COMPOSE_FILE="$BASE_DIR/../docker/docker-compose.prod.yml" ;;
  *) echo "Unknown environment: $ENVIRONMENT"; exit 1 ;;
esac

docker compose -f "$COMPOSE_FILE" up -d --build
echo "Deployment started for $ENVIRONMENT"
