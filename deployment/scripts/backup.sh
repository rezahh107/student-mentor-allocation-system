#!/usr/bin/env bash
# REQUIRES: pip install -e .[dev] (AGENTS.md::8 Testing & CI Gates)
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <destination-dir> <file> [file...]" >&2
  exit 64
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DESTINATION="$1"
shift

exec python -m phase7_release.cli backup --destination "${DESTINATION}" "$@"
