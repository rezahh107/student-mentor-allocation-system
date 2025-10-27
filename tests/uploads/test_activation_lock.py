from __future__ import annotations

import io
from datetime import datetime
from uuid import uuid4

import pytest
from fakeredis import FakeStrictRedis
from prometheus_client import CollectorRegistry

from sma.phase2_uploads.clock import BAKU_TZ, FrozenClock
from sma.phase2_uploads.config import UploadsConfig
from sma.phase2_uploads.errors import UploadError
from sma.phase2_uploads.metrics import UploadsMetrics
from sma.phase2_uploads.repository import create_sqlite_repository
from sma.phase2_uploads.service import UploadContext, UploadService
from sma.phase2_uploads.storage import AtomicStorage
from sma.phase2_uploads.validator import CSVValidator

CSV_BODY = (
    "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
    "1,123,09123456789,0012345678,علی,اکبری\r\n"
).encode("utf-8")


def _make_context(*, year: int, rid: str, namespace: str) -> UploadContext:
    return UploadContext(
        profile="ROSTER_V1",
        year=year,
        filename="upload.csv",
        rid=rid,
        namespace=namespace,
        idempotency_key=uuid4().hex,
    )


def test_activation_single_roster_per_year(tmp_path) -> None:
    service, repository, redis_client = _build_service(tmp_path / "case1")
    first = service.upload(_make_context(year=1402, rid="RID-1", namespace="ns1"), io.BytesIO(CSV_BODY))
    activated = service.activate(first.id, rid="RID-activate", namespace="ns1")
    assert activated.status == "active"

    second_context = _make_context(year=1402, rid="RID-2", namespace="ns2")
    second_record = service.upload(second_context, io.BytesIO(CSV_BODY))
    with pytest.raises(UploadError) as exc:
        service.activate(second_record.id, rid="RID-activate-2", namespace="ns2")
    assert exc.value.envelope.code == "UPLOAD_ACTIVATION_CONFLICT"
    repository.drop_schema()
    redis_client.flushall()


def test_activation_lock_conflict(tmp_path) -> None:
    service, repository, redis_client = _build_service(tmp_path / "case2")
    context = _make_context(year=1403, rid="RID-lock", namespace="ns-lock")
    record = service.upload(context, io.BytesIO(CSV_BODY))
    lock_key = service._activation_lock_key(record.year)
    redis_client.set(lock_key, "busy")
    with pytest.raises(UploadError) as exc:
        service.activate(record.id, rid="RID-lock-2", namespace="ns-lock")
    assert exc.value.envelope.code == "UPLOAD_ACTIVATION_CONFLICT"
    assert redis_client.get(lock_key) == b"busy"
    repository.drop_schema()
    redis_client.flushall()


def _build_service(base_dir) -> tuple[UploadService, object, FakeStrictRedis]:
    base_path = base_dir
    base_path.mkdir(parents=True, exist_ok=True)
    config = UploadsConfig.from_dict(
        {
            "base_dir": base_path,
            "storage_dir": base_path / "storage",
            "manifest_dir": base_path / "manifests",
            "metrics_token": "token",
            "namespace": f"ns-{uuid4().hex[:8]}",
        }
    )
    config.ensure_directories()
    repository = create_sqlite_repository(str(base_path / "uploads.db"))
    redis_client = FakeStrictRedis()
    metrics = UploadsMetrics(CollectorRegistry())
    clock = FrozenClock(datetime(2024, 1, 1, tzinfo=BAKU_TZ))
    service = UploadService(
        config=config,
        repository=repository,
        storage=AtomicStorage(config.storage_dir),
        validator=CSVValidator(),
        redis_client=redis_client,
        metrics=metrics,
        clock=clock,
    )
    return service, repository, redis_client
