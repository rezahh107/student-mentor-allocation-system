"""آزمون‌های هستهٔ سبک برای اطمینان از صحت نگاشت‌های عادی‌سازی."""
from __future__ import annotations

from typing import Iterable

import pytest

from src.core import enums


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Girl", 0),
        ("مرد", 1),
        ("ذكور", 1),
        ("خانوم", 0),
    ],
)
def test_gender_normalization(raw: str, expected: int) -> None:
    """ورودی‌های متنوع باید به مقدار باینری صحیح نگاشت شوند."""

    key = raw.lower()
    assert enums.GENDER_NORMALIZATION_MAP[key] == expected


def test_counter_prefix_values() -> None:
    """پیش‌شمارهٔ شمارنده باید دقیقاً دو مقدار مجاز داشته باشد."""

    assert set(enums.COUNTER_PREFIX.keys()) == {0, 1}
    assert set(enums.COUNTER_PREFIX.values()) == {357, 373}


def test_registration_statuses_cover_expected_values() -> None:
    """تمام حالت‌های مهم ثبت‌نام باید در نگاشت موجود باشند."""

    required: Iterable[str] = ("approved", "hakmat", "منتظر")
    for value in required:
        assert value in enums.REG_STATUS_NORMALIZATION_MAP
