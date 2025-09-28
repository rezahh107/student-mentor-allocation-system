from prometheus_client import CollectorRegistry

from src.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics


def test_retry_and_exhaustion_metrics() -> None:
    registry = CollectorRegistry()
    metrics = CounterRuntimeMetrics(registry)
    metrics.record_alloc("success")
    metrics.record_retry("counter_allocate", attempts=3)
    metrics.record_exhausted("02", 1)

    collected = {metric.name: metric for metric in registry.collect()}
    alloc_samples = collected["counter_alloc"].samples
    assert any(sample.labels.get("status") == "success" and sample.value == 1.0 for sample in alloc_samples if sample.name.endswith("_total"))
    retry_samples = collected["counter_retry"].samples
    assert any(
        sample.labels.get("operation") == "counter_allocate" and sample.value == 3.0
        for sample in retry_samples
        if sample.name.endswith("_total")
    )
    exhausted_samples = collected["counter_exhausted"].samples
    assert any(
        sample.labels.get("year_code") == "02" and sample.labels.get("gender") == "1" and sample.value == 1.0
        for sample in exhausted_samples
        if sample.name.endswith("_total")
    )
