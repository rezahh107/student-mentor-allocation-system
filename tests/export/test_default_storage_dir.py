from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from hashlib import blake2s
from pathlib import Path
from io import StringIO

import pytest
from prometheus_client import CollectorRegistry

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow

_ANCHOR = "AGENTS.md::Atomic I/O & Determinism"


def _namespace(seed: str) -> str:
    digest = blake2s(seed.encode("utf-8"), digest_size=6).hexdigest()
    return f"default-storage-{digest}"


def _rows(year: int, center: int | None):
    return [
        {
            "national_id": "=001",
            "counter": "+140257300",
            "first_name": "علی",
            "last_name": "كاظمی",
            "gender": 0,
            "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
            "reg_center": 1,
            "reg_status": 1,
            "group_code": 5,
            "student_type": 0,
            "school_code": 123,
            "mentor_id": "m-1",
            "mentor_name": "=cmd|' /C calc'!A0",
            "mentor_mobile": "09120000000",
            "allocation_date": "2023-01-01T00:00:00Z",
            "year_code": str(year),
        }
    ]


def test_atomic_export_to_default_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed = os.environ.get("PYTEST_CURRENT_TEST", "default-storage")
    namespace = _namespace(seed)
    tokens_env = f"TOKENS_{namespace.replace('-', '_')}"
    signing_env = f"SIGNING_{namespace.replace('-', '_')}"
    tokens_payload = json.dumps(
        [
            {"value": "service-token-xyz123456789", "role": "ADMIN"},
            {"value": "metrics-token-xyz987654321", "role": "METRICS_RO", "metrics_only": True},
        ],
        ensure_ascii=False,
    )
    signing_payload = json.dumps(
        [
            {"kid": "primary", "secret": "K" * 48, "state": "active"},
        ],
        ensure_ascii=False,
    )
    monkeypatch.setenv(tokens_env, tokens_payload)
    monkeypatch.setenv(signing_env, signing_payload)
    monkeypatch.delenv("EXPORT_STORAGE_DIR", raising=False)
    monkeypatch.setenv("METRICS_TOKEN", "metrics-token-xyz987654321")
    monkeypatch.setattr(
        "phase6_import_to_sabt.app.app_factory._project_root",
        lambda: tmp_path,
    )
    config_payload = {
        "redis": {
            "dsn": "redis://localhost:6379/0",
            "namespace": namespace,
            "operation_timeout": 0.2,
        },
        "database": {
            "dsn": "postgresql://localhost/test",
            "statement_timeout_ms": 500,
        },
        "auth": {
            "metrics_token": "metrics-token-xyz987654321",
            "service_token": "service-token-xyz123456789",
            "tokens_env_var": tokens_env,
            "download_signing_keys_env_var": signing_env,
        },
        "ratelimit": {
            "namespace": namespace,
            "requests": 50,
            "window_seconds": 60,
            "penalty_seconds": 60,
        },
        "observability": {
            "service_name": "import-to-sabt",
            "metrics_namespace": namespace,
        },
        "timezone": "Asia/Tehran",
        "enable_debug_logs": False,
        "enable_diagnostics": True,
    }
    config = AppConfig.model_validate(config_payload)
    clock = FixedClock(datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc))
    timer = DeterministicTimer([0.001] * 32)
    metrics = build_metrics(namespace, registry=CollectorRegistry())
    rate_store = InMemoryKeyValueStore(f"{namespace}:rate", clock)
    idem_store = InMemoryKeyValueStore(f"{namespace}:idem", clock)
    app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
    )
    storage_root = Path(app.state.storage_root)
    assert storage_root == tmp_path / "storage" / "exports"
    assert storage_root.exists(), storage_root

    rename_calls: list[tuple[Path, Path]] = []
    fsync_calls: list[int] = []
    from sma.phase6_import_to_sabt.xlsx import utils as xlsx_utils

    original_replace = xlsx_utils.os.replace
    original_fsync = xlsx_utils.os.fsync

    def _record_replace(src: str, dst: str) -> None:
        rename_calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    def _record_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        original_fsync(fd)

    monkeypatch.setattr(xlsx_utils.os, "replace", _record_replace)
    monkeypatch.setattr(xlsx_utils.os, "fsync", _record_fsync)

    export_metrics = build_import_export_metrics(CollectorRegistry())
    workflow = ImportToSabtWorkflow(
        storage_dir=storage_root,
        clock=clock,
        metrics=export_metrics,
        data_provider=_rows,
    )
    record = workflow.create_export(year=1402, file_format="csv")
    artifact_path = record.artifact_path
    payload = artifact_path.read_bytes()

    assert artifact_path.parent == storage_root
    assert artifact_path.exists(), artifact_path
    assert b"\r\n" in payload, payload
    assert b"\n" not in payload.replace(b"\r\n", b""), payload

    table = list(csv.reader(StringIO(payload.decode("utf-8"))))
    assert table[1][12].startswith("'"), table

    assert not artifact_path.with_suffix(artifact_path.suffix + ".part").exists()
    assert rename_calls, _ANCHOR
    assert any(sma.suffix == ".part" and dst == artifact_path for src, dst in rename_calls), rename_calls
    assert fsync_calls, _ANCHOR
