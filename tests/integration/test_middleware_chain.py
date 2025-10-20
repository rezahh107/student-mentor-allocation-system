"""Middleware ordering guardrails for the ImportToSabt FastAPI application."""

from __future__ import annotations

import pytest

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.config import AppConfig, AuthConfig, DatabaseConfig, RedisConfig


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.middleware
@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
async def test_middleware_chain_enforces_ratelimit_priority(
    clean_redis_state,
    clean_db_state,
    middleware_order_validator,
    get_debug_context,
) -> None:
    """Ensure RateLimit → Idempotency → Auth executes in the documented order.

    Example:
        >>> # Fixture usage inside async pytest
        >>> # (executed under pytest with shared Redis/DB state)
        >>> ...  # doctest: +SKIP
    """

    clean_db_state.record_query("BEGIN -- middleware chain warmup")
    config = AppConfig(
        redis=RedisConfig(dsn="redis://localhost:6379/0", namespace=clean_redis_state.namespace),
        database=DatabaseConfig(dsn="postgresql://example.local/test"),
        auth=AuthConfig(metrics_token="توکن-متریک-پایش", service_token="توکن-سرویس-ادغام"),
    )
    app = create_application(config=config)
    chain_snapshot = [entry.cls.__name__ for entry in app.user_middleware]
    diagnostics = get_debug_context(
        request={"method": "POST", "path": "/exports"},
        response={},
        extra={"middleware": chain_snapshot},
    )
    try:
        middleware_order_validator(app)
    except AssertionError as exc:
        pytest.fail(f"ترتیب میان‌افزار نادرست است: {diagnostics}")

    assert "RateLimitMiddleware" in chain_snapshot, diagnostics
    assert diagnostics["middleware"][0] != diagnostics["middleware"][-1], diagnostics
