from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Iterable

import pytest

from sma.debug.debug_context import DebugContext
from sma._local_fakeredis import FakeStrictRedis


@pytest.fixture
def debug_ctx(request):
    redis = FakeStrictRedis()
    audit_events: list[dict[str, Any]] = []

    def scan(pattern: str) -> Iterable[str]:
        return redis.scan_iter(match=pattern)

    context = DebugContext(
        rid=request.node.name,
        operation=request.function.__name__ if getattr(request, "function", None) else request.node.name,
        namespace=request.module.__name__,
        redis_scan=scan,
        audit_events=lambda: list(audit_events),
    )

    request.node.debug_ctx = context

    container = SimpleNamespace(ctx=context, redis=redis, audit=audit_events)
    try:
        yield container
    finally:
        redis.flushdb()
        container.audit.clear()
        context.http_attempts.clear()
        context.last_error = None


def pytest_runtest_makereport(item, call):  # pragma: no cover - pytest hook
    if call.when != "call" or call.excinfo is None:
        return
    context: DebugContext | None = getattr(item, "debug_ctx", None)
    if not context:
        return
    try:
        payload = context.snapshot()
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001 - best effort reporting
        serialized = f"<debug-context-error:{exc}>"
    original = call.excinfo.value.args
    call.excinfo.value.args = (*original, f"\nDebugContext: {serialized}")
