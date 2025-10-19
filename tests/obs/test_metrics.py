from __future__ import annotations

from prometheus_client import CollectorRegistry

from tools.reqs_doctor.obs import DoctorMetrics


def test_metrics_counters():
    registry = CollectorRegistry()
    metrics = DoctorMetrics(registry)
    metrics.observe_plan()
    metrics.observe_fix()
    metrics.observe_retry_exhaustion()
    samples = {}
    for metric in registry.collect():
        metric_samples = getattr(metric, "samples")
        values = {}
        if isinstance(metric_samples, dict):
            for label_key, value in metric_samples.items():
                if hasattr(label_key, "items"):
                    labels = tuple(sorted(label_key.items()))
                else:
                    labels = tuple(label_key)
                values[labels] = value
        else:
            for sample in metric_samples:
                if hasattr(sample, "labels"):
                    labels = sample.labels
                    value = sample.value
                else:
                    _, labels, value, *_rest = sample
                values[tuple(sorted(labels.items()))] = value
        samples[metric.name] = values
    assert samples["reqs_doctor_plan_generated_total"][()] == 1.0
    assert samples["reqs_doctor_fix_applied_total"][()] == 1.0
    assert samples["reqs_doctor_retry_exhaustion_total"][()] == 1.0
