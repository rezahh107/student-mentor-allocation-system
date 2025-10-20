from __future__ import annotations

import datetime as dt

from sma.phase6_import_to_sabt.app.clock import FixedClock


def test_returns_injected_instant(clock_test_context):
    reference = dt.datetime(2024, 3, 20, 12, 30, 45, tzinfo=dt.timezone.utc)
    clock = FixedClock(instant=reference)

    result = clock_test_context["retry"](clock.now)

    assert result is reference or result == reference, (
        "Injected instant mismatch",
        clock_test_context["get_debug_context"](),
    )


def test_accepts_naive_datetime(clock_test_context):
    reference = dt.datetime(2024, 3, 20, 16, 0, 0)
    clock = FixedClock(instant=reference)

    result = clock_test_context["retry"](clock.now)

    assert result.tzinfo is None, clock_test_context["get_debug_context"]()
    assert result == reference, clock_test_context["get_debug_context"]()
