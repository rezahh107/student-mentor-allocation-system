import pytest

from sma.domain.student.mobile import MobileValidationError, normalize_mobile


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("۰۹‌۱۲٣۴۵۶۷۸۹", "09123456789"),
        ("٠٩١٢٣٤٥٦٧٨٩", "09123456789"),
        ("  \u200f۰۹۱۲۳۴۵۶۷۸۹  ", "09123456789"),
    ],
)
def test_mixed_digits_and_zw_cleaned(raw: str, expected: str) -> None:
    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize("invalid", [None, "", "۰۹", "9123456789", "09123x67890"])
def test_invalid_numbers_raise(invalid: str | None) -> None:
    if invalid is None or invalid.strip() == "":
        assert normalize_mobile(invalid) is None
        return
    with pytest.raises(MobileValidationError) as exc:
        normalize_mobile(invalid)
    assert "نامعتبر" in str(exc.value)
