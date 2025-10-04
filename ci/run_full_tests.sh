#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

rm -rf test-results htmlcov
mkdir -p test-results

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=0
export PYTHONWARNINGS=default
export PYTHONHASHSEED=0

pytest "$@"
