from __future__ import annotations

from sma.ci_orchestrator.middleware import middleware_order


def test_middleware_order_ci():
    assert middleware_order() == ["RateLimit", "Idempotency", "Auth"]
