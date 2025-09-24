from __future__ import annotations

import pytest

from src.infrastructure.resilience.retry import retry


def test_retry_raises_last_exception() -> None:
    call_count = {"value": 0}

    @retry(attempts=2, exceptions=(ValueError,))
    def flaky() -> None:
        call_count["value"] += 1
        raise ValueError("خطای نمونه")

    with pytest.raises(ValueError):
        flaky()

    assert call_count["value"] == 2


def test_retry_guard_without_exception_records_message() -> None:
    @retry(attempts=0)
    def never_called() -> None:
        raise AssertionError("این تابع نباید فراخوانی شود")

    with pytest.raises(RuntimeError, match="هیچ استثنایی"):
        never_called()
