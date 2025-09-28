from __future__ import annotations

import pytest

from src.hardened_api.middleware import (
    ensure_rate_limit_config_restored,
    RateLimitConfig,
    RateLimitRule,
    rate_limit_config_guard,
    restore_rate_limit_config,
    snapshot_rate_limit_config,
)


def test_rate_limit_config_snapshot() -> None:
    config = RateLimitConfig(
        default_rule=RateLimitRule(requests=10, window_seconds=1.0),
        per_route={"/counter/allocate": RateLimitRule(requests=5, window_seconds=1.0)},
        fail_open=False,
    )
    snapshot = snapshot_rate_limit_config(config)

    config.default_rule.requests = 20
    with pytest.raises(AssertionError):
        ensure_rate_limit_config_restored(config, snapshot, context="unit-test")

    restore_rate_limit_config(config, snapshot)
    ensure_rate_limit_config_restored(config, snapshot)

    with rate_limit_config_guard(config) as guarded:
        guarded.fail_open = True

    assert config.fail_open is False
