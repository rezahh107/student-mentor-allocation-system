"""Integration guardrails for ASGI middleware ordering."""

from __future__ import annotations

from typing import List

import pytest

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    RateLimitConfig,
    RedisConfig,
)


@pytest.mark.integration
@pytest.mark.middleware
def test_middleware_order_is_expected(
    clean_state,
    middleware_order_validator,
    get_debug_context,
    timing_control,
) -> None:
    """Ensure RateLimit → Idempotency → Auth ordering never regresses."""

    namespace = f"{clean_state['redis'].namespace}:middleware"
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
        ratelimit=RateLimitConfig(namespace=f"{namespace}:rl", requests=5, window_seconds=60),
        enable_diagnostics=True,
    )

    app = create_application(config=config)

    expected_prefix: List[str] = [
        "RateLimitMiddleware",
        "IdempotencyMiddleware",
        "AuthMiddleware",
    ]

    attempts: list[list[str]] = []
    for _, jitter in enumerate((0.0, 0.001, 0.002), start=1):
        names = [middleware.cls.__name__ for middleware in app.user_middleware]
        attempts.append(names)
        try:
            start_index = names.index(expected_prefix[0])
        except ValueError:
            start_index = -1
        if start_index >= 0 and names[start_index : start_index + len(expected_prefix)] == expected_prefix:
            break
        timing_control.advance(jitter)
    else:  # pragma: no cover - defensive diagnostic branch
        diagnostics = get_debug_context(
            request={"path": "/middleware-check", "method": "GET"},
            response={"expected": expected_prefix},
            extra={
                "namespace": namespace,
                "attempts": attempts,
            },
        )
        pytest.fail(f"ترتیب میان‌افزار نادرست است: {diagnostics}")

    middleware_order_validator(app)
