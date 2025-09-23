#!/usr/bin/env bash
set -euo pipefail
URL=${1:-http://localhost:8000/metrics}
curl -fsS "$URL" >/dev/null && echo OK || (echo FAIL && exit 1)
