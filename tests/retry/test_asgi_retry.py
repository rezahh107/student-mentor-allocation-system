from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.phase6_import_to_sabt.obs.metrics import build_metrics
from tests.helpers import RetryExhaustedError, request_with_retry


@pytest.mark.integration
def test_retry_attempts_and_exhaustion_metrics(cleanup_fixtures) -> None:
    namespace = cleanup_fixtures.namespace
    metrics = build_metrics(namespace, registry=cleanup_fixtures.registry)

    attempts: dict[str, int] = {"count": 0}
    app = FastAPI()

    @app.post("/jobs")
    async def run_jobs() -> JSONResponse:  # pragma: no cover - exercised via httpx transport
        attempts["count"] += 1
        if attempts["count"] < 3:
            return JSONResponse(status_code=429, content={"detail": "rate-limit"})
        return JSONResponse(status_code=200, content={"ok": True})

    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "retry-test"}

    response, context = request_with_retry(
        app,
        "POST",
        "/jobs",
        headers=headers,
        json={"payload": "value"},
        max_attempts=3,
        metrics=metrics,
        namespace=namespace,
        operation="phase6.jobs",
    )
    assert response.status_code == 200, context.as_dict()
    assert [attempt.status_code for attempt in context.attempts] == [429, 429, 200], context.as_dict()
    assert context.jitter_seed == f"{namespace}:phase6.jobs:/jobs"

    attempts["count"] = 0
    other_response, other_context = request_with_retry(
        app,
        "POST",
        "/jobs",
        headers=headers,
        json={"payload": "value"},
        max_attempts=3,
        metrics=metrics,
        namespace=namespace,
        operation="phase6.jobs",
    )
    assert other_response.status_code == 200
    assert [round(item.delay_seconds, 6) for item in other_context.attempts] == [
        round(item.delay_seconds, 6) for item in context.attempts
    ], {
        "first": context.as_dict(),
        "second": other_context.as_dict(),
    }

    attempts["count"] = 0
    with pytest.raises(RetryExhaustedError) as excinfo:
        request_with_retry(
            app,
            "POST",
            "/jobs",
            headers=headers,
            json={"payload": "value"},
            max_attempts=2,
            metrics=metrics,
            namespace=namespace,
            operation="phase6.jobs",
        )
    exhausted_context = excinfo.value.context
    assert [attempt.status_code for attempt in exhausted_context.attempts] == [429, 429], exhausted_context.as_dict()
    assert exhausted_context.last_error == "status:429", exhausted_context.as_dict()
