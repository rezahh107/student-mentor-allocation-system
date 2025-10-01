from __future__ import annotations

import itertools
from typing import Iterable

import numpy as np
import pytest

from src.shared.counter_rules import COUNTER_PREFIX_MAP, gender_prefix, stable_counter_hash


def _iter_invalid_counters() -> Iterable[str]:
    base = [
        "",
        "0",
        "00000000",
        "20373333",
        "aa3570000",
        "223570000",
        "9912345",
        "2200000000",
        "2200000a00",
    ]
    return base


@pytest.mark.parametrize("rows", [256, 512])
def test_counter_regex_accepts_valid_dataset(integration_context, large_dataset, rows):
    """Validate that canonical counters for real datasets always pass regex checks."""

    integration_context.clear_state()
    slice_df = large_dataset.head(rows)

    for gender, counter in zip(slice_df["gender"], slice_df["counter"], strict=True):
        assert integration_context.validate_counter_format(
            "sabt_counter",
            counter,
            gender_code=int(gender),
        ), integration_context.format_debug(
            "Valid counter rejected",
            counter=counter,
            gender=int(gender),
        )

    expected_valid = rows
    assert integration_context.telemetry["valid_counters"] == expected_valid, integration_context.format_debug(
        "Telemetry mismatch for valid counters",
        expected=expected_valid,
        telemetry=integration_context.telemetry,
    )


def test_counter_regex_rejects_invalid_values(integration_context):
    """Ensure malformed counters fail validation with detailed telemetry."""

    integration_context.clear_state()
    invalid_values = list(_iter_invalid_counters())

    for value in invalid_values:
        assert not integration_context.validate_counter_format(
            "sabt_counter",
            value,
            gender_code=0,
        ), integration_context.format_debug(
            "Invalid counter unexpectedly passed",
            value=value,
        )

    assert integration_context.telemetry["counter_validations"] == len(invalid_values), integration_context.format_debug(
        "Counter validation count mismatch",
        expected=len(invalid_values),
        telemetry=integration_context.telemetry,
    )
    assert integration_context.telemetry["valid_counters"] == 0, integration_context.format_debug(
        "Invalid counters reported as valid",
        telemetry=integration_context.telemetry,
    )


def test_counter_validation_handles_edge_cases(integration_context):
    """Cover None, zero-width, mixed digits, and very long strings defensively."""

    integration_context.clear_state()
    edge_cases = [None, "۰", "\u200c", "0", " 3730000 ", "=SUM(A1:A2)", "373" * 10]

    for value in edge_cases:
        is_valid = integration_context.validate_counter_format(
            "sabt_counter",
            value,
            gender_code=1,
        )
        assert not is_valid, integration_context.format_debug(
            "Edge case incorrectly accepted",
            value=value,
            telemetry=integration_context.telemetry,
        )

    assert integration_context.telemetry["validation_errors"] == 0, integration_context.format_debug(
        "Unexpected validation errors encountered",
        telemetry=integration_context.telemetry,
    )


def test_counter_format_consistency_with_gender_prefix(integration_context):
    """Cross-check regex expectations against gender prefix mapping and stable hash."""

    integration_context.clear_state()
    genders = list(COUNTER_PREFIX_MAP.keys())
    seeds = [stable_counter_hash(f"seed-{idx}") % 10_000 for idx in range(5)]

    for gender, seed in itertools.product(genders, seeds):
        prefix = gender_prefix(gender)
        counter = f"24{prefix}{seed:04d}"
        assert integration_context.validate_counter_format(
            "sabt_counter",
            counter,
            gender_code=gender,
        ), integration_context.format_debug(
            "Generated counter failed validation",
            counter=counter,
            gender=gender,
            seed=seed,
        )

    assert integration_context.telemetry["valid_counters"] == len(genders) * len(seeds), integration_context.format_debug(
        "Generated counters telemetry mismatch",
        telemetry=integration_context.telemetry,
    )


def test_counter_validation_concurrency_safety(integration_context):
    """Simulate concurrent validations with deterministic jitter and namespace isolation."""

    integration_context.clear_state()

    payloads = [
        ("sabt_counter", f"23{COUNTER_PREFIX_MAP[gender]}{idx:04d}", gender)
        for gender in COUNTER_PREFIX_MAP
        for idx in range(32)
    ]

    rng = np.random.default_rng(seed=42)
    rng.shuffle(payloads)

    for counter_type, value, gender in payloads:
        integration_context.call_with_retry(
            lambda v=value, g=gender: integration_context.validate_counter_format(
                counter_type,
                v,
                gender_code=g,
            ),
            label="counter_validate",
        )

    assert integration_context.telemetry["counter_validations"] == len(payloads), integration_context.format_debug(
        "Total validations mismatch after concurrent simulation",
        expected=len(payloads),
        telemetry=integration_context.telemetry,
    )
    assert integration_context.telemetry["valid_counters"] == len(payloads), integration_context.format_debug(
        "Concurrent valid counters reported incorrectly",
        telemetry=integration_context.telemetry,
    )
