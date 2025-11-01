"""Shared helpers for performance metrics persistence in CI."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_METRICS_PATH = Path("test-results/performance-metrics.json")
DEFAULT_BUDGETS_PATH = Path("test-results/export.json")


def metrics_output_path() -> Path:
    """Return the configured metrics path (defaults to ``test-results``)."""

    return Path(os.getenv("PYTEST_PERF_METRICS_PATH", str(DEFAULT_METRICS_PATH)))


def budgets_output_path() -> Path:
    """Return the budgets summary path respecting CI overrides."""

    return Path(os.getenv("PYTEST_PERF_BUDGETS_PATH", str(DEFAULT_BUDGETS_PATH)))


def persist_budget_summary(summary: Mapping[str, Any]) -> None:
    """Serialise *summary* to the budgets output path using UTF-8."""

    path = budgets_output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(summary), ensure_ascii=False, indent=2), encoding="utf-8")


def load_metrics(path: Path | None = None) -> Mapping[str, Any]:
    """Load metrics JSON for validation scripts."""

    target = Path(path or metrics_output_path())
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):  # pragma: no cover - defensive guard
        raise TypeError("metrics payload must be a mapping")
    return data


__all__ = [
    "DEFAULT_BUDGETS_PATH",
    "DEFAULT_METRICS_PATH",
    "budgets_output_path",
    "load_metrics",
    "metrics_output_path",
    "persist_budget_summary",
]
