"""Security regression tests against Persian-specific injection vectors."""

from __future__ import annotations

import time
from typing import Callable, Iterator, TypeVar

import pytest

from sma.phase6_import_to_sabt.sanitization import deterministic_jitter
from sma.security.hardening import check_persian_injection
from sma.phase6_import_to_sabt.xlsx.sanitize import safe_cell
from tests.fixtures.state import CleanupFixtures


@pytest.fixture(name="security_state")
def fixture_security_state(cleanup_fixtures: CleanupFixtures) -> Iterator[CleanupFixtures]:
    """Reset shared state before and after security hardening tests."""

    cleanup_fixtures.flush_state()
    yield cleanup_fixtures
    cleanup_fixtures.flush_state()


T = TypeVar("T")


def _retry(operation: Callable[[], T], *, attempts: int, seed: str) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - defensive path
            last_error = exc
            time.sleep(deterministic_jitter(0.01 * attempt, attempt, seed))
    if last_error is not None:
        raise last_error
    raise RuntimeError("عملیات بدون نتیجه پایان یافت")


@pytest.mark.integration
@pytest.mark.security
@pytest.mark.timeout(10)
def test_persian_sql_injection_prevention(security_state: CleanupFixtures) -> None:
    """Verify Persian characters cannot bypass SQL injection detection.

    Example:
        >>> # Run inside pytest to validate injection filters
        >>> check_persian_injection('SELECT * FROM users')
        False
    """

    payloads = [
        "; DROP TABLE students; --",
        "«DELETE FROM users»",  # Persian guillemets should still be blocked.
        "‹UNION SELECT›",  # Half-angle brackets exercise RTL punctuation.
    ]
    results = {
        payload: _retry(lambda p=payload: check_persian_injection(p), attempts=2, seed=f"sql:{security_state.namespace}:{idx}")
        for idx, payload in enumerate(payloads)
    }
    context = security_state.context(results=results)
    assert all(result is False for result in results.values()), f"الگوی تزریق شناسایی نشد: {context}"
    safe_sample = _retry(lambda: check_persian_injection("ثبت‌نام مرکز تهران"), attempts=1, seed=f"sql:{security_state.namespace}:safe")
    assert safe_sample is True, f"ورودی سالم به اشتباه مسدود شد: {context}"


@pytest.mark.integration
@pytest.mark.security
@pytest.mark.timeout(10)
def test_excel_formula_injection(security_state: CleanupFixtures) -> None:
    """Ensure Excel formula injections are quoted for Persian end-users.

    Example:
        >>> safe_cell('=cmd|/c calc')
        "'=cmd|/c calc"
    """

    risky_values = [
        "=cmd|' /c calc'!A0",
        "+SUM(A1:A2)",
        "-HYPERLINK('http://example.com','کلیک')",  # Persian label must still quote.
        "@حمله",
    ]
    sanitized = {
        value: _retry(lambda v=value: safe_cell(v), attempts=3, seed=f"excel:{security_state.namespace}:{idx}")
        for idx, value in enumerate(risky_values)
    }
    context = security_state.context(sanitized=sanitized)
    assert all(value.startswith("'") for value in sanitized.values()), f"فرمول مخرب بدون پیشوند ایمن باقی مانده: {context}"
    assert all(original != sanitized[original] for original in sanitized), f"پاک‌سازی تغییری ایجاد نکرد: {context}"
