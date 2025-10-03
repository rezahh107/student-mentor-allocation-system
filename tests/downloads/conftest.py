from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phase6_import_to_sabt.clock import FixedClock
from phase6_import_to_sabt.download_api import (
    DownloadMetrics,
    DownloadRetryPolicy,
    DownloadSettings,
    DownloadTokenPayload,
    create_download_router,
    encode_download_token,
)

pytest_plugins = ("tests.fixtures.state",)


@dataclass(slots=True)
class DownloadTestEnv:
    app: FastAPI
    client: TestClient
    metrics: DownloadMetrics
    settings: DownloadSettings
    secret: bytes
    clock: FixedClock
    namespace: str
    workspace: Path


@pytest.fixture
def download_env(cleanup_fixtures) -> Iterator[DownloadTestEnv]:
    cleanup_fixtures.flush_state()
    secret = b"download-secret"
    clock = FixedClock(instant=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc))
    workspace_root = cleanup_fixtures.base_dir
    workspace_root.mkdir(parents=True, exist_ok=True)
    namespace_dir = workspace_root / cleanup_fixtures.namespace
    namespace_dir.mkdir(parents=True, exist_ok=True)
    metrics = DownloadMetrics(cleanup_fixtures.registry)
    settings = DownloadSettings(
        workspace_root=workspace_root,
        secret=secret,
        retry=DownloadRetryPolicy(attempts=3, base_delay=0.0001),
    )

    async def _no_sleep(_: float) -> None:
        return None

    app = FastAPI()
    router = create_download_router(settings=settings, clock=clock, metrics=metrics, sleeper=_no_sleep)
    app.include_router(router)
    app.state.storage_root = workspace_root
    app.state.download_metrics = metrics

    with TestClient(app) as client:
        yield DownloadTestEnv(
            app=app,
            client=client,
            metrics=metrics,
            settings=settings,
            secret=secret,
            clock=clock,
            namespace=cleanup_fixtures.namespace,
            workspace=namespace_dir,
        )

    cleanup_fixtures.flush_state()


def write_manifest(base: Path, *, filename: str, sha256: str, byte_size: int) -> None:
    payload = {
        "profile": "SABT_V1",
        "filters": {"year": 1402, "center": None},
        "snapshot": {"marker": "snapshot", "created_at": "2024-01-01T00:00:00+00:00"},
        "generated_at": "2024-01-01T00:00:00+00:00",
        "total_rows": 1,
        "files": [
            {
                "name": filename,
                "sha256": sha256,
                "row_count": 1,
                "byte_size": byte_size,
                "sheets": [],
            }
        ],
        "metadata": {"version": "v1", "files_order": [filename]},
        "format": "csv",
        "excel_safety": {"crlf": True, "bom": False},
    }
    manifest_path = base / "export_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def build_token(
    *,
    env: DownloadTestEnv,
    filename: str,
    sha256: str,
    size: int,
    expires_in: int = 600,
    namespace: str | None = None,
) -> str:
    now_ts = int(env.clock.now().timestamp())
    payload = DownloadTokenPayload(
        namespace=namespace or env.namespace,
        filename=filename,
        sha256=sha256,
        size=size,
        exp=now_ts + expires_in,
        version="v1",
        created_at="2024-01-01T00:00:00+00:00",
    )
    return encode_download_token(payload, secret=env.secret)


def write_artifact(namespace_dir: Path, filename: str, content: bytes) -> str:
    path = namespace_dir / filename
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    write_manifest(namespace_dir, filename=filename, sha256=digest, byte_size=len(content))
    return digest
