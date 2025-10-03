from __future__ import annotations

import random
import time
from typing import Callable

import pytest

from shared.counter_rules import COUNTER_PREFIX_MAP, COUNTER_REGEX, gender_prefix, validate_counter


def _retry(action: Callable[[], None], *, attempts: int = 3, base_delay: float = 0.0005) -> None:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            action()
            return
        except AssertionError as exc:
            errors.append(str(exc))
            if attempt == attempts:
                raise AssertionError("; ".join(errors))
            delay = base_delay * (2 ** (attempt - 1)) + (attempt * 0.0001)
            time.sleep(delay)


@pytest.mark.parametrize("gender,expected", list(COUNTER_PREFIX_MAP.items()))
def test_gender_prefix_matches_map(gender: int, expected: str) -> None:
    assert gender_prefix(gender) == expected


def test_validate_counter_accepts_valid_samples() -> None:
    samples = []
    rng = random.Random(0)
    for gender, prefix in COUNTER_PREFIX_MAP.items():
        for seq in (0, 1, 9999):
            year = f"{rng.randint(0, 99):02d}"
            samples.append(f"{year}{prefix}{seq:04d}")

    def _assert_valid() -> None:
        for sample in samples:
            result = validate_counter(sample)
            assert COUNTER_REGEX.fullmatch(result), f"Regex mismatch: {sample} -> {result}"

    _retry(_assert_valid)


@pytest.mark.parametrize(
    "candidate",
    [
        "abcdefgh",
        "۱۴۰۰۴۴۴۴",
        "990123456",
        "99035700000",
    ],
)
def test_validate_counter_rejects_invalid(candidate: str) -> None:
    with pytest.raises(ValueError):
        validate_counter(candidate)
