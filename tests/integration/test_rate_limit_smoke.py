"""Smoke test for rate limiting without relying on external services."""

from __future__ import annotations

from typing import List

import pytest
from starlette.testclient import TestClient

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    RateLimitConfig,
    RedisConfig,
)


@pytest.mark.integration
@pytest.mark.http
def test_rate_limit_smoke(
    clean_state,
    get_debug_context,
    timing_control,
) -> None:
    """Multiple health checks should not crash and may surface 429 deterministically."""

    namespace = f"{clean_state['redis'].namespace}:ratelimit"
    config = AppConfig(
        redis=RedisConfig(
            dsn="redis://localhost:6379/0",
            namespace=namespace,
            operation_timeout=0.2,
        ),
        database=DatabaseConfig(dsn="postgresql+psycopg://example.local/test"),
        auth=AuthConfig(
            metrics_token="metrics-token",
            service_token="service-token",
        ),
        ratelimit=RateLimitConfig(
            namespace=f"{namespace}:rl",
            requests=3,
            window_seconds=60,
            penalty_seconds=60,
        ),
        enable_diagnostics=True,
    )
    app = create_application(config=config)
    client = TestClient(app)

    try:
        responses: List[int] = []
        for attempt in range(5):
            timing_control.advance(0.05)
            response = client.get(
                "/healthz",
                headers={"X-Client-ID": f"client-{attempt}-{namespace}"},
            )
            responses.append(response.status_code)
            if response.status_code == 429:
                break

        final_status = responses[-1]
        diagnostics = get_debug_context(
            request={"path": "/healthz", "method": "GET"},
            response={"status": final_status},
            extra={"namespace": namespace, "statuses": responses},
        )
        assert final_status in (200, 429), f"Unexpected health check status: {diagnostics}"
    finally:
        client.close()
