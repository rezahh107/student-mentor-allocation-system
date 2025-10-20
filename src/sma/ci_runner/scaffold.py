"""File scaffolding helpers for deterministic CI assets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from jinja2 import Environment, StrictUndefined

from .fs_atomic import atomic_write_text

TEMPLATES = {
    "Makefile": """
.PHONY: init pr full smoke lint clean artifacts

init:
\tpython -m ci_runner init

pr:
\tpython -m ci_runner pr

full:
\tpython -m ci_runner full

smoke:
\tpython -m ci_runner smoke

lint:
\tpre-commit run --all-files

clean:
\trm -rf artifacts .pytest_cache .mypy_cache htmlcov

artifacts:
\t@ls -R artifacts
""",
    "pytest.ini": """
[pytest]
addopts = -q --strict-markers --strict-config --durations=25 --color=yes --maxfail=1 \
          --json-report --json-report-file=artifacts/pytest.json \
          --cov=sma --cov-report=xml:artifacts/coverage.xml --cov-report=html:artifacts/htmlcov \
          --junitxml=artifacts/junit.xml
minversion = 7.0
testpaths = tests
markers =
    slow: marks tests as slow
    perf: performance tests
    e2e: end-to-end tests
    legacy_fixed: legacy deterministic scenarios
    smoke: critical smoke subset
""",
    ".pre-commit-config.yaml": """
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.7
    hooks:
      - id: ruff
        args: ["--fix"]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.8
    hooks:
      - id: bandit
        args: ["-q", "-r", "src"]
  - repo: https://github.com/pypa/pip-audit
    rev: v2.7.3
    hooks:
      - id: pip-audit
        args: ["--requirement", "requirements-dev.in", "--constraint", "constraints-dev.txt", "--output", "artifacts/pip-audit.json", "--format", "json"]
""",
    "requirements-dev.in": """
-r requirements.in
pip-tools==7.5.1
pytest==8.4.2
pytest-asyncio==0.23.7
pytest-cov==5.0.0
pytest-xdist==3.5.0
pytest-json-report==1.5.0
coverage[toml]==7.4.4
ruff==0.5.5
mypy==1.10.0
pre-commit==3.7.1
pip-audit==2.7.3
bandit==1.7.9
freezegun==1.4.0
fakeredis==2.30.3
GitPython==3.1.43
pipdeptree==2.23.1
""",
    "scripts/ci.sh": """
#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Tehran"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m ci_runner pr "$@"
""",
    "scripts/nightly.sh": """
#!/usr/bin/env bash
set -euo pipefail
export TZ="Asia/Tehran"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m ci_runner full "$@"
""",
    "scripts/verify_env.py": """
from __future__ import annotations

import json
import os
import platform
import sys


def main() -> None:
    payload = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "tz": os.getenv("TZ", "Asia/Tehran"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
""",
    ".github/workflows/ci.yml": """
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: ["*"]

jobs:
  pr-gate:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    env:
      TZ: Asia/Tehran
      PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - name: Install project
        run: |
          python -m pip install --upgrade pip
          python -m ci_runner init
      - name: Run PR gate
        run: |
          python -m ci_runner pr
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: ci-artifacts
          path: artifacts
          if-no-files-found: warn
""",
    ".github/workflows/nightly.yml": """
name: Nightly

on:
  schedule:
    - cron: "30 20 * * *"  # Asia/Tehran friendly midnight
  workflow_dispatch:

jobs:
  nightly:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    env:
      TZ: Asia/Tehran
      PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - name: Install project
        run: |
          python -m pip install --upgrade pip
          python -m ci_runner init
      - name: Run full suite
        run: |
          python -m ci_runner full
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: nightly-artifacts
          path: artifacts
          if-no-files-found: warn
""",
}


def _render_template(content: str, **context: str) -> str:
    env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(content)
    return template.render(**context).strip() + "\n"


def scaffold(paths: Iterable[str] | None = None, force: bool = False) -> list[Path]:
    """Create missing CI files using atomic writes."""

    emitted: list[Path] = []
    selected = TEMPLATES if paths is None else {key: TEMPLATES[key] for key in paths if key in TEMPLATES}
    for rel_path, template in selected.items():
        target = Path(rel_path)
        if target.exists() and not force:
            continue
        rendered = _render_template(template)
        atomic_write_text(target, rendered)
        emitted.append(target)
        if target.suffix == ".sh":
            target.chmod(0o755)
    return emitted
