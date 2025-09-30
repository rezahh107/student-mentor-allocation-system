from __future__ import annotations

import io
import json
import logging
import uuid
from types import SimpleNamespace

import pytest

from src.app.bootstrap_logging import bootstrap_logging
from src.app.context import set_debug_context
from src.debug.debug_context import DebugContextFactory
from src.fakeredis import FakeStrictRedis
from src.logging.json_logger import LogEnricher


@pytest.fixture
def redis_client() -> FakeStrictRedis:
    client = FakeStrictRedis()
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()


def _build_request(rid: str) -> SimpleNamespace:
    def endpoint() -> None:  # pragma: no cover - used for metadata only
        return None

    scope = {"path": "/auth/callback", "endpoint": endpoint}
    return SimpleNamespace(
        headers={"X-Request-ID": rid},
        scope=scope,
        state=SimpleNamespace(),
        app=SimpleNamespace(title="sso"),
    )


def test_auto_enriches_and_masks(redis_client: FakeStrictRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    root_logger = logging.getLogger()
    initial_filters = list(root_logger.filters)
    monkeypatch.setenv("DEBUG_CONTEXT_ENABLE", "true")
    bootstrap_logging()
    handler_stream = io.StringIO()
    handler = logging.StreamHandler(handler_stream)
    handler.setFormatter(logging.Formatter("%(message)s|%(debug_context)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    redis_key = f"sso_session:{uuid.uuid4().hex}"
    redis_client.set(redis_key, "token")
    audit_events = [
        {
            "id": 1,
            "action": "AUTHN_FAIL",
            "correlation_id": "email@example.com",
            "ts": "2024-03-21T09:00:00+00:00",
        }
    ]
    factory = DebugContextFactory(
        redis=redis_client,
        audit_fetcher=lambda: list(audit_events),
        namespace="tests.debug",
    )
    request = _build_request("rid-test")
    try:
        ctx = factory(request)
        root_logger.info("PHASE10_DEBUG", extra={"rid": ctx.rid})
        captured = handler_stream.getvalue()
        assert captured.strip(), "Missing log output"
        assert redis_key in captured, f"Redis key not found. Context: {captured}"
        assert "email@example.com" not in captured, f"PII leaked. Context: {captured}"
        payload = captured.split("|", 1)[1].strip()
        snapshot = json.loads(payload)
        assert snapshot["rid"] == "rid-test", f"Unexpected rid. Snapshot: {snapshot}"
        assert snapshot["namespace"] == "tests.debug", f"Unexpected namespace. Snapshot: {snapshot}"
        assert snapshot["audit_events"][0]["cid"] != "email@example.com", f"CID leaked. Snapshot: {snapshot}"
        set_debug_context(None)
        handler_stream.truncate(0)
        handler_stream.seek(0)
        root_logger.info("PHASE10_NOCTX")
        fallback = handler_stream.getvalue().strip().split("|")[-1]
        assert fallback == "{}", f"Fallback context invalid. Context: {fallback}"
    finally:
        root_logger.removeHandler(handler)
        handler.close()
        set_debug_context(None)
        for filt in list(root_logger.filters):
            if isinstance(filt, LogEnricher) and filt not in initial_filters:
                root_logger.removeFilter(filt)
        for existing_handler in list(root_logger.handlers):
            for filt in list(existing_handler.filters):
                if isinstance(filt, LogEnricher):
                    existing_handler.removeFilter(filt)
