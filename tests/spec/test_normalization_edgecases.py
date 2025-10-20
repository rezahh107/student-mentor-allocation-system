"""Edge-case coverage for Persian text and Excel-safe normalization."""

from __future__ import annotations

import hashlib
from typing import Iterator

import pytest

from sma.phase6_import_to_sabt.sanitization import (
    guard_formula,
    sanitize_phone,
    sanitize_text,
    secure_digest,
)
from tests.fixtures.state import CleanupFixtures


@pytest.fixture(name="normalization_state")
def fixture_normalization_state(cleanup_fixtures: CleanupFixtures) -> Iterator[CleanupFixtures]:
    cleanup_fixtures.flush_state()
    yield cleanup_fixtures
    cleanup_fixtures.flush_state()


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_sanitize_text_handles_null_and_zero(normalization_state: CleanupFixtures) -> None:
    cases = {
        None: "",
        "": "",
        "   ": "",
        "0": "0",
        "۰۰۰": "000",
        "٠١٢٣": "0123",
    }
    results = {raw: sanitize_text(raw) for raw in cases}
    context = normalization_state.context(results=results, cases=cases)
    assert results == cases, context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_sanitize_text_nfkc_digit_fold_and_letters(normalization_state: CleanupFixtures) -> None:
    raw = "\u200cكلاس يک ۱۲۳٤۵۶۷۸۹"
    sanitized = sanitize_text(raw)
    expected = "کلاس یک 123456789"
    context = normalization_state.context(raw=raw, sanitized=sanitized, expected=expected)
    assert sanitized == expected, context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_sanitize_phone_mixed_digits(normalization_state: CleanupFixtures) -> None:
    raw = "۰۹١٢٣٤٥٦٧٨٩"
    normalized = sanitize_phone(raw)
    context = normalization_state.context(raw=raw, normalized=normalized)
    assert normalized == "09123456789", context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_guard_formula_blocks_injection(normalization_state: CleanupFixtures) -> None:
    risky_values = {"=cmd": "'=cmd", "+SUM": "'+SUM", "safe": "safe", "'@": "'@"}
    results = {value: guard_formula(value) for value in risky_values}
    context = normalization_state.context(results=results)
    assert results == risky_values, context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_secure_digest_streams_large_payload(normalization_state: CleanupFixtures) -> None:
    chunk = ("داده" * 4096).encode("utf-8")
    hasher = hashlib.sha256()

    def generator() -> Iterator[bytes]:
        for _ in range(32):
            hasher.update(chunk)
            yield chunk

    digest_observed = secure_digest(generator())
    digest_expected = hasher.hexdigest()
    context = normalization_state.context(
        digest_expected=digest_expected,
        digest_observed=digest_observed,
        sample_length=len(chunk),
    )
    assert digest_observed == digest_expected, context
