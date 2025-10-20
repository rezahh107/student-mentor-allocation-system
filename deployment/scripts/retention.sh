#!/usr/bin/env bash
# REQUIRES: pip install -e .[dev] (AGENTS.md::8 Testing & CI Gates)
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <root> <max-age-days> <max-total-bytes> [--enforce]" >&2
  exit 64
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROOT="$1"
AGE="$2"
LIMIT="$3"
shift 3

flag="--dry-run"
for arg in "$@"; do
  if [[ "$arg" == "--enforce" ]]; then
    flag="--enforce"
  fi
done

exec python -m phase7_release.cli retention --root "${ROOT}" --max-age-days "${AGE}" --max-total-bytes "${LIMIT}" ${flag}
