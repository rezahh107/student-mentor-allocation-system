#!/usr/bin/env bash
# REQUIRES: pip install -e .[dev] (AGENTS.md::8 Testing & CI Gates)
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <manifest> <destination-dir>" >&2
  exit 64
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec python -m phase7_release.cli restore --manifest "$1" --destination "$2"
