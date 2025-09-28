from __future__ import annotations

import io
import pytest

from phase2_uploads.errors import UploadError
from phase2_uploads.validator import CSVValidator
from phase2_uploads.service import UploadContext


def write_csv(tmp_path, content: bytes):
    path = tmp_path / "file.csv"
    path.write_bytes(content)
    return path


def test_reject_non_utf8_crlf_missing_header(tmp_path):
    bad_content = "ستون۱,ستون۲\n۱,۲\n".encode("utf-16")
    path = write_csv(tmp_path, bad_content)
    validator = CSVValidator()
    with pytest.raises(UploadError) as exc:
        validator.validate(path)
    assert "UTF8" in str(exc.value.envelope.details.get("reason", ""))


def test_reject_non_crlf(tmp_path, service):
    content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\n"
        "1,1,09120000000,001,علی,کاظمی\n"
    ).encode("utf-8")
    context = UploadContext(
        profile="ROSTER_V1",
        year=1400,
        filename="bad.csv",
        rid="RID-CRLF",
        namespace="csv",
        idempotency_key="csv-crlf",
    )
    with pytest.raises(UploadError) as exc:
        service.upload(context, io.BytesIO(content))
    assert exc.value.envelope.details["reason"] == "CRLF_REQUIRED"


def test_school_code_positive(tmp_path):
    content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,0,09123456789,1234567890,حسین,اکبری\r\n"
    ).encode("utf-8")
    validator = CSVValidator()
    path = write_csv(tmp_path, content)
    with pytest.raises(UploadError) as exc:
        validator.validate(path)
    assert exc.value.envelope.details["reason"] == "SCHOOL_CODE_POSITIVE"


def test_nfkc_unify_yek_strip_zw_digit_folding(tmp_path):
    content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,۱۲۳,۰۹۱۲۳۴۵۶۷۸۹,0012345678,\u200cكيوان,علي\r\n"
    ).encode("utf-8")
    validator = CSVValidator(preview_rows=2)
    result = validator.validate(write_csv(tmp_path, content))
    assert result.record_count == 1
    preview = result.preview_rows[0]
    assert preview["first_name"] == "کیوان"
    assert preview["last_name"] == "علی"
    assert preview["mobile"] == "09123456789"
    assert preview["school_code"] == "123"


def test_formula_guard_on_text_fields(tmp_path):
    content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,123,09123456789,0012345678,=cmd,احمد\r\n"
    ).encode("utf-8")
    validator = CSVValidator()
    with pytest.raises(UploadError) as exc:
        validator.validate(write_csv(tmp_path, content))
    assert exc.value.envelope.details["reason"] == "FORMULA_GUARD"
