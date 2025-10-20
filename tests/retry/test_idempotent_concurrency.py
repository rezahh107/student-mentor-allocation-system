from __future__ import annotations

import threading
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sma.core.clock import DEFAULT_TIMEZONE, FrozenClock
from sma.utils.retry import retry


class ConflictError(RuntimeError):
    pass


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_only_one_request_commits() -> None:
    clock = FrozenClock(timezone=ZoneInfo(DEFAULT_TIMEZONE))
    clock.set(datetime(2024, 3, 20, 12, 0, tzinfo=ZoneInfo(DEFAULT_TIMEZONE)))
    lock = threading.Lock()
    state: dict[str, object] = {"result": None, "creator": None}
    conflict_counts: Counter[str] = Counter()
    successes: list[str] = []
    barrier = threading.Barrier(3)

    def sleeper(seconds: float) -> None:
        clock.tick(seconds)

    def process(worker_id: str) -> dict[str, object]:
        barrier.wait()
        def operation() -> dict[str, object]:
            with lock:
                if state["result"] is None:
                    payload = {"rid": worker_id, "status": "created"}
                    state["result"] = payload
                    state["creator"] = worker_id
                    return payload
                if conflict_counts[worker_id] == 0:
                    conflict_counts[worker_id] += 1
                    raise ConflictError("duplicate request")
                assert state["result"] is not None
                return state["result"]  # type: ignore[return-value]
        result = retry(
            operation,
            attempts=3,
            base_ms=100,
            max_ms=800,
            jitter_seed="idempotency",
            clock=clock,
            retryable=(ConflictError,),
            op="idempotent_post",
            correlation_id=worker_id,
            sleeper=sleeper,
        )
        successes.append(result["rid"])  # type: ignore[index]
        return result

    workers = [f"worker-{idx}" for idx in range(3)]
    threads = [threading.Thread(target=process, args=(worker,)) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert state["result"] is not None
    assert state["creator"] in workers
    assert successes.count(state["creator"]) == len(workers)
    for worker in workers:
        if worker != state["creator"]:
            assert conflict_counts[worker] == 1
