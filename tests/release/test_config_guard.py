from __future__ import annotations

import importlib
import sys
import types

import pytest


@pytest.fixture
def clean_state():
    yield


def test_snapshot_restore_and_reject_unknowns(clean_state):
    if "opentelemetry" not in sys.modules:
        sys.modules["opentelemetry"] = types.ModuleType("opentelemetry")
        trace_module = types.ModuleType("opentelemetry.trace")
        trace_module.SpanKind = object()  # minimal stub
        sys.modules["opentelemetry.trace"] = trace_module
    if "redis" not in sys.modules:
        redis_module = types.ModuleType("redis")
        asyncio_module = types.ModuleType("redis.asyncio")
        class _Redis:  # pragma: no cover - placeholder
            ...

        asyncio_module.Redis = _Redis
        sys.modules["redis"] = redis_module
        sys.modules["redis.asyncio"] = asyncio_module
    middleware = importlib.import_module("src.hardened_api.middleware")
    RateLimitConfig = middleware.RateLimitConfig
    RateLimitRule = middleware.RateLimitRule
    rate_limit_config_guard = middleware.rate_limit_config_guard
    snapshot_rate_limit_config = middleware.snapshot_rate_limit_config

    config = RateLimitConfig(
        default_rule=RateLimitRule(requests=10, window_seconds=1.0),
        per_route={"/exports": RateLimitRule(requests=5, window_seconds=1.0)},
    )
    snapshot = snapshot_rate_limit_config(config)
    with rate_limit_config_guard(config):
        config.per_route["/readyz"] = RateLimitRule(requests=3, window_seconds=1.0)
    assert snapshot_rate_limit_config(config) == snapshot
