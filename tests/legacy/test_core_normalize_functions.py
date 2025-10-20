import pytest

from sma.core import normalize

from sma.core import normalize


def _build_valid_national_id(seed: str = "001234567") -> str:
    digits = seed.strip().replace(" ", "")
    assert digits.isdigit() and len(digits) == 9
    for check_digit in range(10):
        candidate = f"{digits}{check_digit}"
        checksum = sum(int(candidate[i]) * (10 - i) for i in range(9))
        remainder = checksum % 11
        expected = remainder if remainder < 2 else 11 - remainder
        if expected == check_digit:
            return candidate
    raise AssertionError("unable to create valid national id")


def test_normalize_gender_and_reg_status() -> None:
    assert normalize.normalize_gender("دختر") == 0
    assert normalize.normalize_gender("boy") == 1
    with pytest.raises(ValueError):
        normalize.normalize_gender(True)
    with pytest.raises(ValueError):
        normalize.normalize_gender(None)
    with pytest.raises(ValueError):
        normalize.normalize_gender(5)
    with pytest.raises(ValueError):
        normalize.normalize_gender("ناشناخته")

    assert normalize.normalize_reg_status("حکمت") == 3
    assert normalize.normalize_reg_status("۰") == 0
    with pytest.raises(ValueError):
        normalize.normalize_reg_status("ناشناخته")
    with pytest.raises(ValueError):
        normalize.normalize_reg_status(True)
    with pytest.raises(ValueError):
        normalize.normalize_reg_status(5)


def test_normalize_reg_center_and_mobile() -> None:
    assert normalize.normalize_reg_center("۲") == 2
    with pytest.raises(ValueError):
        normalize.normalize_reg_center(None)
    with pytest.raises(ValueError):
        normalize.normalize_reg_center(True)
    with pytest.raises(ValueError):
        normalize.normalize_reg_center(5)
    with pytest.raises(ValueError):
        normalize.normalize_reg_center("مرکز")

    assert normalize.normalize_mobile("00989123456789") == "09123456789"
    assert normalize.normalize_mobile("0989123456789") == "09123456789"
    assert normalize.normalize_mobile("989123456789") == "09123456789"
    with pytest.raises(ValueError):
        normalize.normalize_mobile("12345")


def test_normalize_school_code_and_sequence() -> None:
    assert normalize.normalize_school_code("۱۲۳۴۵") == 12345
    assert normalize.normalize_school_code(None) is None
    with pytest.raises(ValueError):
        normalize.normalize_school_code(True)
    with pytest.raises(ValueError):
        normalize.normalize_school_code("کد")

    assert normalize.normalize_int_sequence([" ۱۲ ", "۰۰۳", None, ""]) == [12, 3]
    with pytest.raises(ValueError):
        normalize.normalize_int_sequence(["الف"])
    with pytest.raises(ValueError):
        normalize.normalize_int_sequence([True])
    with pytest.raises(ValueError):
        normalize.normalize_int_sequence(True)
    with pytest.raises(ValueError):
        normalize.normalize_int_sequence("۱۲،۱۳")
    with pytest.raises(ValueError):
        normalize.normalize_int_sequence(123)


def test_normalize_name_strips_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    assert normalize.normalize_name(" زهرا‌یوسفی ") == "زهرایوسفی"
    assert normalize.normalize_name("  علی   محمدی  ") == "علی محمدی"
    assert normalize.normalize_name("كیان") == "کیان"
    assert normalize.normalize_name(None) is None
    with pytest.raises(ValueError):
        normalize.normalize_name(True)
    messages = [record.getMessage() for record in caplog.records]
    assert any("name.cleaned" in msg for msg in messages)
    assert any("name.arabic_letters" in msg for msg in messages)


def test_normalize_name_empty_after_cleanup(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    assert normalize.normalize_name("\u200c\u200c") is None
    assert any("name.empty_after_clean" in record.getMessage() for record in caplog.records)


def test_derive_student_type_with_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def provider(year: int):
        assert year == 1402
        return ["۱۲۳۴۵", "00100"]

    result = normalize.derive_student_type("۱۲۳۴۵", None, roster_year=1402, provider=provider)
    assert result == 1

    result = normalize.derive_student_type("54321", ["۰۰۱۰۰"], roster_year=None, provider=None)
    assert result == 0


def test_normalize_national_id_validations() -> None:
    valid = _build_valid_national_id()
    assert normalize.normalize_national_id(valid) == valid
    with pytest.raises(ValueError):
        normalize.normalize_national_id("۱۲۳")
    with pytest.raises(ValueError):
        normalize.normalize_national_id(True)
    with pytest.raises(ValueError):
        normalize.normalize_national_id("1234567890")


def test_derive_student_type_provider_error(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")

    def broken_provider(year: int):
        raise RuntimeError("boom")

    result = normalize.derive_student_type("۱۲۳۴۵", None, roster_year=1402, provider=broken_provider)
    assert result == 0
    assert any("student_type.provider_error" in record.getMessage() for record in caplog.records)
