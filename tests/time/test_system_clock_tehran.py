from __future__ import annotations

import datetime as dt

import pytest
from freezegun import freeze_time
from zoneinfo import ZoneInfo

from phase6_import_to_sabt.app.clock import build_system_clock


def test_now_tz_tehran(clock_test_context):
    context_debug = clock_test_context["get_debug_context"]
    with freeze_time("2022-03-21T08:30:00+00:00"):
        clock = build_system_clock("Asia/Tehran")
        result = clock_test_context["retry"](clock.now)

    expected = dt.datetime(2022, 3, 21, 12, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    assert result.tzinfo is not None, context_debug()
    assert getattr(result.tzinfo, "key", None) == "Asia/Tehran", context_debug()
    assert result == expected, (result.isoformat(), expected.isoformat(), context_debug())
    assert clock.timezone_name == "Asia/Tehran", context_debug()
    assert clock_test_context["middleware_chain"] == ("RateLimit", "Idempotency", "Auth")


@pytest.mark.parametrize(
    "raw_tz, expected_key",
    [
        ("  Asia/Tehran\u200c", "Asia/Tehran"),
    ],
)
def test_timezone_normalization(clock_test_context, raw_tz, expected_key):
    with freeze_time("2023-01-01T00:00:00+00:00"):
        clock = build_system_clock(raw_tz)
        result = clock_test_context["retry"](clock.now)

    assert getattr(result.tzinfo, "key", None) == expected_key, clock_test_context["get_debug_context"]()


@pytest.mark.parametrize(
    "invalid",
    [None, "", "0", "Invalid/Zone", "Asia/" + "Tehran" * 60],
)
def test_invalid_timezone_raises_persian_error(clock_test_context, invalid):
    with pytest.raises(ValueError) as excinfo:
        build_system_clock(invalid)  # type: ignore[arg-type]

    message = str(excinfo.value)
    assert "منطقهٔ زمانی نامعتبر است" in message, clock_test_context["get_debug_context"]()
