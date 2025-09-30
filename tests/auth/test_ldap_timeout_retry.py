from __future__ import annotations

import asyncio

import pytest

from auth.errors import ProviderError
from auth.ldap_adapter import LdapGroupMapper, LdapSettings
from auth.metrics import AuthMetrics
from auth.utils import exponential_backoff


def test_retry_then_success_and_exhaustion_metrics() -> None:
    async def _run() -> None:
        metrics_success = AuthMetrics.build()
        sleep_success: list[float] = []
        attempts = {"count": 0}

        async def fetch_success(user: str):
            attempts["count"] += 1
            if attempts["count"] <= 2:
                raise asyncio.TimeoutError
            return ["MANAGER:456"]

        async def sleep_record(delay: float) -> None:
            sleep_success.append(delay)

        mapper_success = LdapGroupMapper(
            fetch_success,
            settings=LdapSettings(timeout_seconds=0.1),
            metrics=metrics_success,
            max_retries=4,
            backoff_seconds=0.05,
            sleep=sleep_record,
        )
        role, scope = await mapper_success({"sub": "user-ldap"}, correlation_id="rid-ldap")
        assert role == "MANAGER"
        assert scope == "456"
        attempts_value = metrics_success.retry_attempts_total.labels(adapter="ldap", reason="timeout")._value.get()
        exhaustion_value = metrics_success.retry_exhaustion_total.labels(adapter="ldap", reason="timeout")._value.get()
        assert attempts_value == 2.0
        assert exhaustion_value == 0.0
        expected_delays = [
            exponential_backoff(0.05, 1, jitter_seed="rid-ldap:timeout"),
            exponential_backoff(0.05, 2, jitter_seed="rid-ldap:timeout"),
        ]
        assert pytest.approx(sleep_success, rel=1e-6) == expected_delays
        registry_success = metrics_success.registry
        sum_success = registry_success.get_sample_value(
            "auth_retry_backoff_seconds_sum",
            {"adapter": "ldap", "reason": "timeout"},
        )
        count_success = registry_success.get_sample_value(
            "auth_retry_backoff_seconds_count",
            {"adapter": "ldap", "reason": "timeout"},
        )
        assert pytest.approx(sum_success, rel=1e-6) == sum(expected_delays)
        assert count_success == 2.0

        metrics_fail = AuthMetrics.build()
        sleep_fail: list[float] = []

        async def fetch_fail(user: str):
            raise asyncio.TimeoutError

        async def sleep_record_fail(delay: float) -> None:
            sleep_fail.append(delay)

        mapper_fail = LdapGroupMapper(
            fetch_fail,
            settings=LdapSettings(timeout_seconds=0.1),
            metrics=metrics_fail,
            max_retries=3,
            backoff_seconds=0.05,
            sleep=sleep_record_fail,
        )
        with pytest.raises(ProviderError) as excinfo:
            await mapper_fail({"sub": "user-fail"}, correlation_id="rid-fail")
        assert excinfo.value.code == "AUTH_LDAP_TIMEOUT"
        attempts_fail = metrics_fail.retry_attempts_total.labels(adapter="ldap", reason="timeout")._value.get()
        exhaustion_fail = metrics_fail.retry_exhaustion_total.labels(adapter="ldap", reason="timeout")._value.get()
        assert attempts_fail == 2.0
        assert exhaustion_fail == 1.0
        expected_fail = [
            exponential_backoff(0.05, 1, jitter_seed="rid-fail:timeout"),
            exponential_backoff(0.05, 2, jitter_seed="rid-fail:timeout"),
        ]
        assert pytest.approx(sleep_fail, rel=1e-6) == expected_fail
        registry_fail = metrics_fail.registry
        sum_fail = registry_fail.get_sample_value(
            "auth_retry_backoff_seconds_sum",
            {"adapter": "ldap", "reason": "timeout"},
        )
        count_fail = registry_fail.get_sample_value(
            "auth_retry_backoff_seconds_count",
            {"adapter": "ldap", "reason": "timeout"},
        )
        assert pytest.approx(sum_fail, rel=1e-6) == sum(expected_fail)
        assert count_fail == 2.0

    asyncio.run(_run())
