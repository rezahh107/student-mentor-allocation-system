from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from auth.errors import ProviderError
from auth.metrics import AuthMetrics
from auth.oidc_adapter import OIDCAdapter
from auth.session_store import SessionStore
from auth.utils import exponential_backoff
from config.env_schema import SSOConfig
from src.fakeredis import FakeStrictRedis

pytest_plugins = ["tests.fixtures.debug_context"]


def test_kid_rotation_success_then_exhaustion_metrics(
    oidc_provider,
    oidc_http_client,
    sso_clock,
    audit_log,
) -> None:
    async def _run() -> None:
        config = SSOConfig.from_env(oidc_provider.env())
        # Scenario 1: rotation succeeds after JWKS refresh
        metrics_success = AuthMetrics.build()
        sleep_success: list[float] = []

        async def sleep_record_success(delay: float) -> None:
            sleep_success.append(delay)

        redis_success = FakeStrictRedis()
        store_success = SessionStore(
            redis_success,
            ttl_seconds=config.session_ttl_seconds,
            clock=sso_clock.clock,
            namespace=f"sso-success-{uuid4().hex}",
        )
        adapter_success = OIDCAdapter(
            settings=config.oidc,
            http_client=oidc_http_client,
            session_store=store_success,
            metrics=metrics_success,
            clock=sso_clock.clock,
            audit_sink=audit_log.sink,
            ldap_mapper=None,
            max_retries=3,
            backoff_seconds=0.05,
            sleep=sleep_record_success,
        )
        oidc_provider.rotate_signing_key("rotated", "rotated-secret", publish=False)
        oidc_provider.queue_jwks(
            [
                [{"kty": "oct", "kid": "mock-key", "k": oidc_provider.client_secret}],
                [{"kty": "oct", "kid": "rotated", "k": "rotated-secret"}],
            ]
        )
        code = oidc_provider.issue_code({"role": "ADMIN", "center_scope": "ALL"})
        session = await adapter_success.authenticate(
            code=code,
            correlation_id="rid-success",
            request_id="rid-success",
        )
        assert session.role == "ADMIN"
        assert metrics_success.retry_attempts_total.labels(adapter="oidc", reason="jwks")._value.get() == 1.0
        assert (
            metrics_success.retry_exhaustion_total.labels(adapter="oidc", reason="jwks")._value.get() == 0.0
        )
        expected_delay = exponential_backoff(0.05, 1, jitter_seed="rid-success:jwks")
        assert pytest.approx(sleep_success, rel=1e-6) == [expected_delay]
        redis_success.flushdb()

        # Scenario 2: repeated mismatch -> exhaustion metrics
        metrics_fail = AuthMetrics.build()
        sleep_fail: list[float] = []

        async def sleep_record_fail(delay: float) -> None:
            sleep_fail.append(delay)

        redis_fail = FakeStrictRedis()
        store_fail = SessionStore(
            redis_fail,
            ttl_seconds=config.session_ttl_seconds,
            clock=sso_clock.clock,
            namespace=f"sso-fail-{uuid4().hex}",
        )
        adapter_fail = OIDCAdapter(
            settings=config.oidc,
            http_client=oidc_http_client,
            session_store=store_fail,
            metrics=metrics_fail,
            clock=sso_clock.clock,
            audit_sink=audit_log.sink,
            ldap_mapper=None,
            max_retries=3,
            backoff_seconds=0.05,
            sleep=sleep_record_fail,
        )
        oidc_provider.rotate_signing_key("exhaust", "exhaust-secret", publish=False)
        oidc_provider.queue_jwks(
            [
                [{"kty": "oct", "kid": "stale", "k": "legacy-secret"}],
                [{"kty": "oct", "kid": "stale", "k": "legacy-secret"}],
                [{"kty": "oct", "kid": "stale", "k": "legacy-secret"}],
            ]
        )
        code_fail = oidc_provider.issue_code({"role": "MANAGER", "center_scope": "123"})
        with pytest.raises(ProviderError) as excinfo:
            await adapter_fail.authenticate(
                code=code_fail,
                correlation_id="rid-fail",
                request_id="rid-fail",
            )
        assert excinfo.value.code == "AUTH_JWKS_EXHAUSTED"
        attempts = metrics_fail.retry_attempts_total.labels(adapter="oidc", reason="jwks")._value.get()
        exhaustion = metrics_fail.retry_exhaustion_total.labels(adapter="oidc", reason="jwks")._value.get()
        assert attempts == 2.0
        assert exhaustion == 1.0
        expected_fail = [
            exponential_backoff(0.05, 1, jitter_seed="rid-fail:jwks"),
            exponential_backoff(0.05, 2, jitter_seed="rid-fail:jwks"),
        ]
        assert pytest.approx(sleep_fail, rel=1e-6) == expected_fail
        registry = metrics_fail.registry
        sum_value = registry.get_sample_value(
            "auth_retry_backoff_seconds_sum",
            {"adapter": "oidc", "reason": "jwks"},
        )
        count_value = registry.get_sample_value(
            "auth_retry_backoff_seconds_count",
            {"adapter": "oidc", "reason": "jwks"},
        )
        assert pytest.approx(sum_value, rel=1e-6) == sum(expected_fail)
        assert count_value == 2.0
        redis_fail.flushdb()

    asyncio.run(_run())
