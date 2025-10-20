from __future__ import annotations

import time

import pytest

from sma.phase6_import_to_sabt.sanitization import guard_formula


@pytest.fixture
def clean_state():
    yield


def test_100k_under_budgets(clean_state):
    values = ["=value" if i % 10 == 0 else "متن" for i in range(100_000)]
    start = time.perf_counter()
    guarded = [guard_formula(value) for value in values]
    duration = time.perf_counter() - start
    assert duration < 1.0
    assert sum(value.startswith("'") for value in guarded) == 10_000
