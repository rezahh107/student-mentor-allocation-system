from automation_audit.api import IdempotencyMiddleware, RateLimitMiddleware, create_app
from automation_audit.auth import AuthMiddleware


def test_middleware_order(redis_client):
    app = create_app(redis_client=redis_client, auth_tokens=["token"], rate_limit_config=None)
    chain = [mw.cls for mw in app.user_middleware]
    assert chain == [RateLimitMiddleware, IdempotencyMiddleware, AuthMiddleware]
