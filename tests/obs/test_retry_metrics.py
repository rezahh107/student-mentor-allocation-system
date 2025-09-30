from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.phase6_import_to_sabt.obs.metrics import build_metrics
from tests.helpers import RetryExhaustedError, request_with_retry


@pytest.mark.observability
def test_retry_metrics_emitted(cleanup_fixtures) -> None:
    namespace = cleanup_fixtures.namespace
    metrics = build_metrics(namespace, registry=cleanup_fixtures.registry)

    attempts: dict[str, int] = {"count": 0}
    app = FastAPI()

    @app.post("/guarded")
    async def guarded() -> JSONResponse:  # pragma: no cover - executed via httpx transport
        attempts["count"] += 1
        if attempts["count"] < 2:
            return JSONResponse(status_code=503, content={"detail": "backend"})
        return JSONResponse(status_code=200, content={"ok": True, "attempt": attempts["count"]})

    response, context = request_with_retry(
        app,
        "POST",
        "/guarded",
        headers={"Authorization": "Bearer metrics"},
        json={"task": "retry"},
        max_attempts=3,
        metrics=metrics,
        namespace=namespace,
        operation="ops.retry",
    )
    assert response.status_code == 200, context.as_dict()
    metric_name = f"{namespace}_retry_attempts_total"
    attempts_total = metrics.registry.get_sample_value(
        metric_name,
        {"operation": "ops.retry", "route": "/guarded"},
    )
    assert attempts_total == float(len(context.attempts)), {
        "samples": list(metrics.registry.collect()),
        "context": context.as_dict(),
    }
    exhausted_metric = f"{namespace}_retry_exhausted_total"
    exhausted_total = metrics.registry.get_sample_value(
        exhausted_metric,
        {"operation": "ops.retry", "route": "/guarded"},
    )
    assert exhausted_total in (None, 0.0)

    attempts["count"] = 0
    with pytest.raises(RetryExhaustedError):
        request_with_retry(
            app,
            "POST",
            "/guarded",
            headers={"Authorization": "Bearer metrics"},
            json={"task": "retry"},
            max_attempts=1,
            metrics=metrics,
            namespace=namespace,
            operation="ops.retry",
        )
    exhausted_total_after = metrics.registry.get_sample_value(
        exhausted_metric,
        {"operation": "ops.retry", "route": "/guarded"},
    )
    assert exhausted_total_after == 1.0, {
        "samples": list(metrics.registry.collect()),
        "namespace": namespace,
    }
