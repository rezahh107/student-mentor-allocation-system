from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sma.ops import metrics

PROMQL_METRIC_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
RESERVED_TOKENS = {
    "sum",
    "rate",
    "histogram_quantile",
    "avg",
    "by",
    "without",
    "max",
    "min",
    "count_over_time",
    "increase",
    "on",
    "ignoring",
    "group_left",
    "group_right",
    "phase",
    "status",
    "kind",
    "type",
    "le",
    "m",
}
ALLOWED_EXTERNAL = {"node_memory_MemAvailable_bytes"}


def _extract_metrics(expr: str) -> set[str]:
    sanitized = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', "", expr)
    candidates = set(PROMQL_METRIC_RE.findall(sanitized))
    return {
        token
        for token in candidates
        if token not in RESERVED_TOKENS and not token.isupper()
    }


def _load_dashboard(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    panels = data["dashboard"].get("panels", [])
    expressions: list[str] = []
    for panel in panels:
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if isinstance(expr, str):
                expressions.append(expr)
    return expressions


def _registered_metric_names() -> set[str]:
    names: set[str] = set()
    for metric_family in metrics.REGISTRY.collect():
        for sample in metric_family.samples:
            names.add(sample.name)
    return names


def _seed_registry() -> None:
    metrics.reset_metrics_registry()
    metrics.EXPORT_JOB_TOTAL.labels(status="completed").inc()
    metrics.EXPORT_DURATION_SECONDS.labels(phase="healthz").observe(0.1)
    metrics.EXPORT_DURATION_SECONDS.labels(phase="ready").observe(0.2)
    metrics.EXPORT_DURATION_SECONDS.labels(phase="upload").observe(0.3)
    metrics.EXPORT_ROWS_TOTAL.labels(type="sabt").inc(10)
    metrics.EXPORT_FILE_BYTES_TOTAL.labels(kind="zip").inc(1024)
    metrics.UPLOAD_ERRORS_TOTAL.labels(type="fatal").inc()
    metrics.UPLOAD_ERRORS_TOTAL.labels(type="soft").inc()


@pytest.fixture(autouse=True)
def reset_registry():
    metrics.reset_metrics_registry()
    yield
    metrics.reset_metrics_registry()


@pytest.mark.observability
@pytest.mark.integration
def test_slo_panels_resolve_metrics():
    _seed_registry()
    expressions = _load_dashboard(Path("ops/dashboards/slo.json"))
    registered = _registered_metric_names() | ALLOWED_EXTERNAL
    missing = []
    for expr in expressions:
        for metric_name in _extract_metrics(expr):
            if metric_name not in registered:
                missing.append((expr, metric_name))
    assert not missing, {
        "missing": missing,
        "registered": sorted(registered),
        "expressions": expressions,
    }


@pytest.mark.observability
@pytest.mark.integration
def test_export_panels_resolve_metrics():
    _seed_registry()
    paths = [
        Path("ops/dashboards/exports.json"),
        Path("ops/dashboards/uploads.json"),
        Path("ops/dashboards/errors.json"),
    ]
    registered = _registered_metric_names() | ALLOWED_EXTERNAL
    missing = []
    for path in paths:
        for expr in _load_dashboard(path):
            for metric_name in _extract_metrics(expr):
                if metric_name not in registered:
                    missing.append((str(path), expr, metric_name))
    assert not missing, {
        "missing": missing,
        "registered": sorted(registered),
    }
