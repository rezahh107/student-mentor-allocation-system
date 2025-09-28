from __future__ import annotations

from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.metrics import ExporterMetrics, reset_registry


def test_registry_fresh_between_tests(prom_registry_reset) -> None:
    registry = CollectorRegistry()
    prom_registry_reset.append(registry)
    metrics = ExporterMetrics(registry)
    metrics.inc_job("success", "csv")
    assert "export_jobs_total" in registry._names_to_collectors  # type: ignore[attr-defined]

    reset_registry(registry)
    assert getattr(registry, "_names_to_collectors", {}) == {}  # type: ignore[attr-defined]

    metrics_after = ExporterMetrics(registry)
    # No ValueError should be raised because registry is clean; verify a metric works again.
    metrics_after.inc_job("success", "csv")
