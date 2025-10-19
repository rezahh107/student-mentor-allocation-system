from __future__ import annotations

from tools.refactor_imports import (
    AuthMiddleware,
    IdempotencyMiddleware,
    IdempotencyStore,
    MiddlewareChain,
    RateLimitMiddleware,
    RequestEnvelope,
)


def test_order_rate_idem_auth(clean_state) -> None:
    store = IdempotencyStore()
    chain = MiddlewareChain(RateLimitMiddleware(5), IdempotencyMiddleware(store), AuthMiddleware())
    request = RequestEnvelope(rid="rid", action="scan", namespace="test")

    def handler(envelope: RequestEnvelope) -> str:
        envelope.trace.append("handler")
        return "ok"

    result = chain.execute(request, handler)
    assert result == "ok"
    assert request.trace == ["rate-limit", "idempotency", "auth", "handler"]
