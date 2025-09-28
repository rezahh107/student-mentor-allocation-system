from automation_audit.debug import get_debug_context
from automation_audit.ratelimit import RateLimitConfig, RateLimiter


def test_context_in_asserts(redis_client):
    limiter = RateLimiter(redis_client, RateLimitConfig())
    context = get_debug_context(redis_client, limiter)
    assert context["middleware_order"] == ["RateLimit", "Idempotency", "Auth"]
    assert context["env"] in {"local", "true"}
