import pytest

from automation_audit.validation import Enrollment


def test_enums():
    with pytest.raises(ValueError):
        Enrollment(reg_center=9, reg_status=0, phone="09123456789").validate()
