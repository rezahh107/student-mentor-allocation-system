from __future__ import annotations

import json

import pytest

pytest_plugins = ["tests.fixtures.debug_context", "pytester"]


def test_snapshot_includes_expected_fields(debug_ctx) -> None:
    ctx = debug_ctx.ctx
    redis = debug_ctx.redis
    audit = debug_ctx.audit

    redis.set("sso_session:test", "value")
    redis.set("idem:abc", "value")
    redis.set("ratelimit:xyz", "value")
    audit.append({"action": "AUTHN_OK", "correlation_id": "user@example.com", "ts": "2024-03-21T09:00:00+00:00"})
    ctx.record_http_attempt(method="post", url="https://idp/token", status=500, duration=0.123456)
    ctx.set_last_error(code="AUTH_FAIL", message="email@example.com should not leak")

    snapshot = ctx.snapshot()
    payload = json.dumps(snapshot, ensure_ascii=False)
    assert "sso_session:test" in snapshot["redis_keys"]
    assert snapshot["audit_events"][-1]["cid"] != "user@example.com"
    assert "email@example.com" not in payload
    assert snapshot["http_attempts"][0]["status"] == 500
    assert snapshot["http_attempts"][0]["method"] == "POST"
    assert snapshot["last_error"]["code"] == "AUTH_FAIL"
    assert snapshot["last_error"]["message"] != "email@example.com should not leak"


def test_attaches_and_masks_no_pii(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        pytest_plugins = ["tests.fixtures.debug_context"]

        def test_failure(debug_ctx):
            ctx = debug_ctx.ctx
            ctx.set_last_error(code="AUTH_FAIL", message="email@example.com")
            assert False
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "DebugContext:" in output
    context_fragment = output.split("DebugContext:", 1)[1]
    assert "email@example.com" not in context_fragment
