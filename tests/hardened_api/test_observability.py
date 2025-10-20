from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from tests.hardened_api.conftest import assert_clean_final_state, setup_test_data
from sma.hardened_api.middleware import ensure_rate_limit_config_restored, snapshot_rate_limit_config
from sma.hardened_api.observability import get_metric, metrics_registry_guard


@pytest.mark.asyncio
async def test_logs_and_metrics(clean_state, client, caplog):
    payload = setup_test_data(unique_suffix="2")
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "Idempotency-Key": "METRICKEY1234567",
        "X-Request-ID": str(uuid.uuid4()),
    }
    with caplog.at_level("INFO", logger="hardened_api"):
        response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    correlation = response.headers["X-Correlation-ID"]
    log_messages = [json.loads(record.message) for record in caplog.records]
    assert any(entry["correlation_id"] == correlation for entry in log_messages)
    assert not any("national_id" in record.message for record in caplog.records)
    http_samples = get_metric("http_requests_total").collect()[0].samples
    assert any(
        sample.labels.get("path") == "/allocations" and sample.labels.get("status") == "200"
        for sample in http_samples
    )
    alloc_samples = get_metric("alloc_attempt_total").collect()[0].samples
    assert any(sample.labels.get("outcome") == "success" for sample in alloc_samples)
    await assert_clean_final_state(client)


def _non_created_sample(sample: Any) -> bool:
    return not sample.name.endswith("_created")


def test_metrics_registry_starts_clean() -> None:
    counter = get_metric("auth_fail_total")
    samples = counter.collect()[0].samples
    assert all(sample.value == 0 for sample in samples if _non_created_sample(sample))


def test_metrics_registry_guard_clears_state() -> None:
    counter = get_metric("auth_fail_total")
    counter.labels(reason="guard-test").inc()
    assert any(
        sample.labels.get("reason") == "guard-test" and sample.value >= 1
        for sample in counter.collect()[0].samples
        if _non_created_sample(sample)
    )
    with metrics_registry_guard():
        pass
    assert all(
        sample.value == 0
        for sample in counter.collect()[0].samples
        if _non_created_sample(sample)
    )


def test_rate_limit_snapshot_detection(app) -> None:
    application = app
    config = application.state.middleware_state.rate_limit_config  # type: ignore[attr-defined]
    snapshot = snapshot_rate_limit_config(config)
    config.default_rule.requests += 1
    with pytest.raises(AssertionError):
        ensure_rate_limit_config_restored(config, snapshot, context="unit-test")
