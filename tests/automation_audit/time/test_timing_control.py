import asyncio

import pytest

from automation_audit.retry import RetryConfig, retry_async


def test_retry_timing(monkeypatch):
    sequence = []

    async def sleeper(delay):
        sequence.append(delay)

    monkeypatch.setattr("automation_audit.retry.random.uniform", lambda a, b: 0)

    async def fail():
        raise RuntimeError

    async def run():
        with pytest.raises(RuntimeError):
            await retry_async(fail, config=RetryConfig(attempts=2, base_delay=0.05, jitter=0.0), sleep=sleeper)

    asyncio.run(run())
    assert sequence == [0.05]
