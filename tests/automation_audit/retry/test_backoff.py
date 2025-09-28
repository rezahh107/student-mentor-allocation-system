import asyncio

import pytest

from automation_audit.retry import RetryConfig, retry_async


def test_backoff_jitter(monkeypatch):
    delays = []

    async def sleeper(delay):
        delays.append(delay)

    monkeypatch.setattr("automation_audit.retry.random.uniform", lambda a, b: 0)

    calls = 0

    async def failing():
        nonlocal calls
        calls += 1
        raise RuntimeError

    async def run():
        with pytest.raises(RuntimeError):
            await retry_async(failing, config=RetryConfig(attempts=2, base_delay=0.1, jitter=0.0), sleep=sleeper)

    asyncio.run(run())
    assert delays[0] == pytest.approx(0.1)
    assert calls == 2
