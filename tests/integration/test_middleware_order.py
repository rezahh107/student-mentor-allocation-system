from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import pytest


class MockMiddleware:
    """Trackable middleware that records entry/exit ordering."""

    def __init__(self, name: str, context) -> None:
        self.name = name
        self.context = context
        self.call_order: list[str] = []
        self.call_count = 0

    async def __call__(self, request, call_next: Callable[[object], Awaitable[object]]):
        self.call_count += 1
        start_marker = f"{self.name}_start"
        self.context.register_middleware_event(start_marker)
        self.call_order.append(start_marker)
        response = await call_next(request)
        end_marker = f"{self.name}_end"
        self.context.register_middleware_event(end_marker)
        self.call_order.append(end_marker)
        return response


@pytest.fixture
def middleware_stack(integration_context):
    return {
        "rate_limit": MockMiddleware("RateLimit", integration_context),
        "idempotency": MockMiddleware("Idempotency", integration_context),
        "auth": MockMiddleware("Auth", integration_context),
    }


@pytest.fixture
def mock_request(integration_context):
    request = integration_context.build_request(
        method="POST",
        path="/api/integration",
        headers={
            "X-API-Key": "test-key",
            "X-Idempotency-Key": integration_context.generate_idempotency_key("idem"),
        },
    )
    return request


@pytest.mark.asyncio
async def test_middleware_execution_order(integration_context, middleware_stack, mock_request):
    """Validate RateLimit → Idempotency → Auth execution order."""

    integration_context.clear_state()

    async def final_handler(request):
        integration_context.register_middleware_event("Handler")
        return {"status": "success"}

    async def auth_chain(request):
        return await middleware_stack["auth"](request, final_handler)

    async def idempotency_chain(request):
        return await middleware_stack["idempotency"](request, auth_chain)

    async def rate_limit_chain(request):
        return await middleware_stack["rate_limit"](request, idempotency_chain)

    result = await integration_context.async_call_with_retry(
        lambda: rate_limit_chain(mock_request),
        label="middleware_order",
    )
    assert result == {"status": "success"}, integration_context.format_debug(
        "Middleware chain failed",
        result=result,
    )

    expected = [
        "RateLimit_start",
        "Idempotency_start",
        "Auth_start",
        "Handler",
        "Auth_end",
        "Idempotency_end",
        "RateLimit_end",
    ]
    assert integration_context.get_middleware_chain() == expected, integration_context.format_debug(
        "Middleware order mismatch",
        recorded=integration_context.get_middleware_chain(),
        expected=expected,
    )


@pytest.mark.asyncio
async def test_rate_limit_blocks_early(integration_context, middleware_stack, mock_request):
    """Rate limiter should short-circuit downstream middleware when quota exceeded."""

    integration_context.clear_state()

    async def rate_limited(request, call_next):
        integration_context.rate_limit_state["blocked"] = True
        integration_context.register_middleware_event("RateLimit_block")
        return {"error": "محدودیت درخواست اعمال شد.", "status": 429}

    middleware_stack["rate_limit"] = rate_limited

    async def auth_chain(request):
        return await middleware_stack["auth"](request, lambda r: {"status": "ok"})

    async def idempotency_chain(request):
        return await middleware_stack["idempotency"](request, auth_chain)

    result = await middleware_stack["rate_limit"](mock_request, idempotency_chain)
    assert result["status"] == 429, integration_context.format_debug(
        "Rate limiter did not block request",
        result=result,
    )
    assert middleware_stack["idempotency"].call_count == 0, integration_context.format_debug(
        "Idempotency middleware executed unexpectedly",
        call_count=middleware_stack["idempotency"].call_count,
    )
    assert middleware_stack["auth"].call_count == 0, integration_context.format_debug(
        "Auth middleware executed unexpectedly",
        call_count=middleware_stack["auth"].call_count,
    )


@pytest.mark.asyncio
async def test_idempotency_deduplication(integration_context, mock_request):
    """Idempotency middleware should deduplicate identical requests."""

    integration_context.clear_state()
    idem_key = integration_context.generate_idempotency_key("dedupe")
    mock_request.headers["X-Idempotency-Key"] = idem_key
    namespace_key = integration_context.redis.namespaced(idem_key)

    async def idempotency_middleware(request, call_next):
        cached = integration_context.idempotency_store.get(namespace_key)
        if cached is not None:
            return cached
        response = await call_next(request)
        integration_context.idempotency_store[namespace_key] = response
        return response

    async def final_handler(request):
        return {
            "status": "created",
            "idempotency_key": request.headers["X-Idempotency-Key"],
        }

    first = await integration_context.async_call_with_retry(
        lambda: idempotency_middleware(mock_request, final_handler),
        label="idem-first",
    )
    second = await integration_context.async_call_with_retry(
        lambda: idempotency_middleware(mock_request, final_handler),
        label="idem-second",
    )

    assert first == second, integration_context.format_debug(
        "Idempotency response mismatch",
        first=first,
        second=second,
    )
    assert integration_context.idempotency_store[namespace_key] == first


@pytest.mark.asyncio
async def test_auth_middleware_validation(integration_context, mock_request):
    """Authentication middleware enforces Persian error messaging and user binding."""

    integration_context.clear_state()

    async def auth_middleware(request, call_next):
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != "valid-key":
            integration_context.register_middleware_event("Auth_reject")
            return {"error": "دسترسی غیرمجاز است.", "status": 401}
        request.user = {"id": 123, "name": "کاربر آزمایشی"}
        return await call_next(request)

    async def success_handler(request):
        return {"status": "ok", "user": request.user}

    mock_request.headers["X-API-Key"] = "invalid"
    denied = await auth_middleware(mock_request, success_handler)
    assert denied["status"] == 401, integration_context.format_debug(
        "Invalid API key should be rejected",
        response=denied,
    )
    assert "دسترسی" in denied["error"]

    mock_request.headers["X-API-Key"] = "valid-key"
    allowed = await auth_middleware(mock_request, success_handler)
    assert allowed["status"] == "ok", integration_context.format_debug(
        "Valid API key rejected",
        response=allowed,
    )
    assert allowed["user"]["id"] == 123


@pytest.mark.asyncio
async def test_concurrent_middleware_safety(integration_context):
    """Concurrent requests receive unique namespaces without race conditions."""

    integration_context.clear_state()

    async def handler(request):
        return {
            "status": "ok",
            "request_id": request.headers["X-Request-ID"],
        }

    requests = [
        integration_context.build_request(method="GET", path=f"/api/{idx}")
        for idx in range(10)
    ]

    async def invoke(req):
        return await integration_context.async_call_with_retry(
            lambda: handler(req),
            label="concurrent-handler",
        )

    results = await asyncio.gather(*[invoke(req) for req in requests])

    assert len(results) == 10, integration_context.format_debug(
        "Unexpected number of responses",
        results=results,
    )
    assert all(result["status"] == "ok" for result in results)
    request_ids = {result["request_id"] for result in results}
    assert len(request_ids) == 10, integration_context.format_debug(
        "Duplicate request identifiers detected",
        request_ids=list(request_ids),
    )
