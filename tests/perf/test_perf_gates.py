from __future__ import annotations

import json
import time
import tracemalloc
from hashlib import blake2s

import pytest

from tests.helpers.http_retry import request_with_retry
from tests.mw.test_middleware_order_all_apps import _build_phase6_app

_ANCHOR = "AGENTS.md::Determinism"
_P95_BUDGET_MS = 200.0
_MEMORY_BUDGET_MB = 300.0
_SUCCESS_STATUS = 200


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        raise ValueError("samples required")
    sorted_samples = sorted(samples)
    position = (len(sorted_samples) - 1) * (percentile / 100.0)
    floor_index = int(position)
    ceil_index = min(floor_index + 1, len(sorted_samples) - 1)
    if floor_index == ceil_index:
        return sorted_samples[floor_index]
    lower_weight = ceil_index - position
    upper_weight = position - floor_index
    return (
        sorted_samples[floor_index] * lower_weight
        + sorted_samples[ceil_index] * upper_weight
    )


@pytest.mark.usefixtures("monkeypatch")
def test_p95_latency_and_memory(monkeypatch) -> None:
    app = _build_phase6_app(monkeypatch)
    headers = {
        "Authorization": "Bearer service-token",
        "Idempotency-Key": f"idem-{blake2s(b'perf', digest_size=4).hexdigest()}",
        "X-Client-ID": "perf-harness",
    }
    durations: list[float] = []
    peak_memory_mb = 0.0
    token_seed = blake2s(b"perf-harness", digest_size=6).hexdigest()
    tracemalloc.start()
    try:
        for attempt_index in range(8):
            start = time.perf_counter()
            response, retry_context = request_with_retry(
                app,
                "POST",
                "/api/jobs",
                headers=headers,
                json={"request_id": f"perf-{token_seed}-{attempt_index}"},
                max_attempts=1,
                namespace=f"perf-{token_seed}",
                jitter_seed=f"perf-{attempt_index}",
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            durations.append(elapsed_ms)
            assert response.status_code == _SUCCESS_STATUS, json.dumps(
                {
                    "evidence": _ANCHOR,
                    "status": response.status_code,
                    "namespace": retry_context.namespace,
                    "attempts": [entry.status_code for entry in retry_context.attempts],
                    "duration_ms": elapsed_ms,
                },
                ensure_ascii=False,
            )
            _, peak_bytes = tracemalloc.get_traced_memory()
            peak_memory_mb = max(peak_memory_mb, peak_bytes / (1024 * 1024))
    finally:
        tracemalloc.stop()

    p95 = _percentile(durations, 95.0)
    context = {
        "evidence": _ANCHOR,
        "durations": durations,
        "p95_ms": p95,
        "peak_memory_mb": peak_memory_mb,
    }
    assert p95 <= _P95_BUDGET_MS, json.dumps(context, ensure_ascii=False)
    assert peak_memory_mb <= _MEMORY_BUDGET_MB, json.dumps(context, ensure_ascii=False)
