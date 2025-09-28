import pytest

from automation_audit.validation import Enrollment


def test_phone_regex():
    Enrollment(reg_center=1, reg_status=1, phone="۰۹۱۲۳۴۵۶۷۸۹").validate()
    with pytest.raises(ValueError):
        Enrollment(reg_center=1, reg_status=1, phone="123").validate()
