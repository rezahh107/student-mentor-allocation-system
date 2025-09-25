"""تست سناریوهای ورودی مرزی برای نرمال‌سازی و اعتبارسنجی."""
from __future__ import annotations

import pytest

from src.phase2_counter_service.errors import CounterServiceError
from src.phase2_counter_service.validation import ensure_valid_inputs, normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("0", "0"),
        ("۰", "0"),
        (" ۰۱۲۳۴۵۶۷۸۹ ", "0123456789"),
        ("۰۱۲۳۴۵۶۷۸۹\u200b", "0123456789"),
        (" " + "۰۱۲۳۴۵۶۷۸۹" * 5 + " ", "0123456789" * 5),
    ],
)
def test_normalize_preserves_expected_ascii(raw: object, expected: str) -> None:
    """NFKC و تبدیل ارقام فارسی باید خروجی قطعی ایجاد کند."""

    assert normalize(raw) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "national_id",
    [
        None,
        "",
        "0",
        "۰",
        "۰۱۲۳۴۵۶۷۸۹\u200c",
        "۰" * 100,
        "0123456789" * 20,
    ],
)
def test_invalid_national_id_edges_raise(national_id: object) -> None:
    """تمام مقادیر ناسازگار باید با پیام فارسی رد شوند."""

    with pytest.raises(CounterServiceError) as excinfo:
        ensure_valid_inputs(national_id, 0, "01")  # type: ignore[arg-type]
    detail = excinfo.value.detail
    assert detail.message_fa == "کد ملی نامعتبر است."
    assert detail.details == "کد ملی باید دقیقا ۱۰ رقم باشد."


@pytest.mark.parametrize(
    "year_code",
    [
        None,
        "",
        "0",
        "۰",
        "۰۱\u200c",
        "۰" * 50,
        "01" * 10,
    ],
)
def test_invalid_year_code_edges_raise(year_code: object) -> None:
    """کد سال باید همیشه دو رقم ASCII پس از نرمال‌سازی باشد."""

    with pytest.raises(CounterServiceError) as excinfo:
        ensure_valid_inputs("0123456789", 0, year_code)  # type: ignore[arg-type]
    detail = excinfo.value.detail
    assert detail.message_fa == "کد سال نامعتبر است."
    assert detail.details == "کد سال باید دقیقا دو رقم باشد."


@pytest.mark.parametrize(
    ("national_id", "year_code"),
    [("۰۱۲۳۴۵۶۷۸۹", "۰۱"), ("0123456789", "01")],
)
def test_valid_inputs_accept_mixed_fa_digits(national_id: str, year_code: str) -> None:
    """ترکیب ارقام فارسی و لاتین باید پس از نرمال‌سازی معتبر باشد."""

    normalized_nid, normalized_year = ensure_valid_inputs(national_id, 1, year_code)
    assert normalized_nid == "0123456789"
    assert normalized_year == "01"
