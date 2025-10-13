from __future__ import annotations

from datetime import datetime

from src.core.clock import FrozenClock, validate_timezone
from src.ops.retry import build_retry_metrics
from windows_launcher.launcher import wait_for_backend


def test_waits_respect_injected_clock():
    tz = validate_timezone("Asia/Tehran")
    clock = FrozenClock(timezone=tz)
    clock.set(datetime(2024, 1, 1, 8, 0, tzinfo=tz))

    attempts: list[int] = []

    def probe(port: int, correlation_id: str) -> bool:
        attempts.append(port)
        return len(attempts) >= 3

    delays: list[float] = []

    def sleeper(seconds: float) -> None:
        delays.append(seconds)
        clock.tick(seconds)

    wait_for_backend(
        28000,
        correlation_id="cid",
        probe=probe,
        sleep=sleeper,
        metrics=build_retry_metrics("launcher_clock"),
        max_attempts=5,
        jitter_base=0.5,
        jitter_cap=1.0,
    )

    assert len(delays) == 2  # two backoff intervals before success
    assert all(delay <= 1.0 for delay in delays)
