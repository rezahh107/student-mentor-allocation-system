from __future__ import annotations

import io
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from fakeredis import FakeStrictRedis
from prometheus_client import CollectorRegistry

from sma.phase2_uploads.config import UploadsConfig
from sma.phase2_uploads.errors import UploadError
from sma.phase2_uploads.clock import BAKU_TZ, FrozenClock
from sma.phase2_uploads.metrics import UploadsMetrics
from sma.phase2_uploads.repository import create_sqlite_repository
from sma.phase2_uploads.service import UploadContext, UploadService
from sma.phase2_uploads.storage import AtomicStorage
from sma.phase2_uploads.validator import CSVValidator


def _make_csv(school_code: str) -> bytes:
    return (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        f"1,{school_code},09123456789,0012345678,علی,اکبری\r\n"
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("raw", "expected_reason"),
    [
        ("0", "SCHOOL_CODE_POSITIVE"),
        ("٠", "SCHOOL_CODE_POSITIVE"),
        ("۰", "SCHOOL_CODE_POSITIVE"),
        ("", "SCHOOL_CODE_REQUIRED"),
        ("   ", "SCHOOL_CODE_REQUIRED"),
        ("None", "SCHOOL_CODE_INVALID"),
    ],
)
def test_school_code_rejections(raw: str, expected_reason: str, tmp_path) -> None:
    validator = CSVValidator()
    with pytest.raises(UploadError) as exc:
        validator.validate(PathHelper.write_csv(_make_csv(raw), tmp_path=tmp_path))
    assert exc.value.envelope.details["reason"] == expected_reason


def test_text_normalization_and_mixed_digits(tmp_path) -> None:
    validator = CSVValidator(preview_rows=1)
    content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,٠٠١٢٣,۰۹۱۲۳۴۵۶۷۸۹,۰۰۱۲۳۴۵۶۷۸۹,\u200cكیان,علي\r\n"
    ).encode("utf-8")
    path = PathHelper.write_csv(content, tmp_path=tmp_path)
    result = validator.validate(path)
    assert result.record_count == 1
    preview = result.preview_rows[0]
    assert preview["first_name"] == "کیان"
    assert preview["last_name"] == "علی"
    assert preview["mobile"] == "09123456789"
    assert preview["school_code"] == "123"
    assert result.excel_safety["normalized"] is True
    assert result.excel_safety["digit_folding"] is True


def test_large_payload_rejected(tmp_path) -> None:
    base_dir = tmp_path / "heavy"
    config = UploadsConfig.from_dict(
        {
            "base_dir": base_dir,
            "storage_dir": base_dir / "storage",
            "manifest_dir": base_dir / "manifests",
            "metrics_token": "token",
            "max_upload_bytes": 64,
            "namespace": "stress",
        }
    )
    config.ensure_directories()
    repository = create_sqlite_repository(str(base_dir / "uploads.db"))
    storage = AtomicStorage(config.storage_dir)
    validator = CSVValidator()
    metrics = UploadsMetrics(CollectorRegistry())
    clock = FrozenClock(datetime(2024, 1, 1, tzinfo=BAKU_TZ))
    redis_client = FakeStrictRedis()
    service = UploadService(
        config=config,
        repository=repository,
        storage=storage,
        validator=validator,
        redis_client=redis_client,
        metrics=metrics,
        clock=clock,
    )
    context = UploadContext(
        profile="ROSTER_V1",
        year=1402,
        filename="heavy.csv",
        rid="RID-heavy",
        namespace="stress",
        idempotency_key=uuid4().hex,
    )
    header = "student_id,school_code,mobile,national_id,first_name,last_name\r\n".encode("utf-8")
    body = ("1,123,09123456789,001,علی,اکبری\r\n" * 4).encode("utf-8")
    content = header + body
    with pytest.raises(UploadError) as exc:
        service.upload(context, io.BytesIO(content))
    assert exc.value.envelope.code == "UPLOAD_SIZE_EXCEEDED"
    repository.drop_schema()
    redis_client.flushall()


def test_validator_normalizes_edge_cases(tmp_path) -> None:
    validator = CSVValidator(preview_rows=3)
    long_text = "الف" * 512
    content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,٠٠٠١,٠٩۱۲۳۴۵۶۷۸۹,\u200c۰۰۱۲۳۴۵۶۷۸۹,\u200cك" + long_text + ",null\r\n"
    ).encode("utf-8")
    path = PathHelper.write_csv(content, tmp_path=tmp_path)
    result = validator.validate(path)
    preview = result.preview_rows[0]
    assert preview["school_code"] == "1", preview
    assert preview["mobile"] == "09123456789", preview
    assert preview["first_name"].startswith("کالف"), preview
    assert "\u200c" not in preview["first_name"], preview
    assert result.record_count == 1
    assert result.excel_safety["formula_guard"] is True


def test_validator_handles_large_file_preview_limits(tmp_path) -> None:
    validator = CSVValidator(preview_rows=5)
    header = "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
    row = "{idx},123,09123456789,0012345678,مینا,یوسفی\r\n"
    payload = header + "".join(row.format(idx=i) for i in range(1, 2001))
    path = PathHelper.write_csv(payload.encode("utf-8"), tmp_path=tmp_path)
    result = validator.validate(path)
    assert result.record_count == 2000
    assert len(result.preview_rows) == 5
    assert result.preview_rows[0]["student_id"] == "1"
    assert result.preview_rows[-1]["student_id"] == "5"


class PathHelper:
    @staticmethod
    def write_csv(content: bytes, *, tmp_path=None):
        from pathlib import Path

        directory = tmp_path or Path.cwd() / "tmp_csv"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"test-{sha256(content).hexdigest()}.csv"
        path.write_bytes(content)
        return path
