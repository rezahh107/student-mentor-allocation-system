import asyncio

import pytest

from automation_audit.metrics import build_metrics
from automation_audit.retry import RetryConfig, retry_async


def test_retry_exhaustion_metrics(metrics):
    async def run():
        async def failing():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await retry_async(failing, config=RetryConfig(attempts=2, base_delay=0.0, jitter=0.0), metrics=metrics, sleep=lambda _: asyncio.sleep(0))
        assert metrics.retry_exhausted._value.get() == 1.0

    asyncio.run(run())


def test_audit_counters(metrics):
    metrics.audit_runs.inc()
    metrics.audit_failures.inc()
    assert metrics.audit_runs._value.get() == 1.0
    assert metrics.audit_failures._value.get() == 1.0
