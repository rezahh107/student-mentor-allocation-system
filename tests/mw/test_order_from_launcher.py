from __future__ import annotations

from sma.infrastructure.api.routes import create_app


def test_chain_preserved():
    app = create_app()
    classes = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert classes[:3] == [
        "RateLimitMiddleware",
        "IdempotencyMiddleware",
        "AuthMiddleware",
    ]
