from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.app.utils import normalize_token
from phase6_import_to_sabt.download_api import DownloadTokenPayload, encode_download_token
from phase6_import_to_sabt.obs.metrics import build_metrics


def _write_manifest(namespace_dir: Path, filename: str, sha256: str, size: int) -> None:
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
                "byte_size": size,
                "sheets": [],
            }
        ],
        "metadata": {"version": "v1", "files_order": [filename]},
        "format": "csv",
        "excel_safety": {"crlf": True},
    }
    (namespace_dir / "export_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def test_middleware_order_download_endpoint(tmp_path_factory: pytest.TempPathFactory) -> None:
    unique = uuid4().hex
    storage_root = tmp_path_factory.mktemp(f"download-{unique}")
    namespace = f"ns-{unique}"
    namespace_dir = storage_root / namespace
    namespace_dir.mkdir(parents=True, exist_ok=True)
    content = b"id,name\r\n1,Ali\r\n"
    file_name = "export.csv"
    file_path = namespace_dir / file_name
    file_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    _write_manifest(namespace_dir, file_name, digest, len(content))

    service_token = f"service-token-{unique}"
    metrics_token = f"metrics-token-{unique}"
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": f"import_to_sabt_{unique}"},
        database={"dsn": "postgresql+asyncpg://localhost/import_to_sabt"},
        auth={
            "metrics_token": metrics_token,
            "service_token": service_token,
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
        enable_diagnostics=True,
    )
    clock = FixedClock(instant=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc))
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_download_{unique}")
    rate_store = InMemoryKeyValueStore(f"rate:{unique}", clock)
    idempotency_store = InMemoryKeyValueStore(f"idem:{unique}", clock)

    app = create_application(
        config=config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idempotency_store,
        readiness_probes={},
    )
    app.state.storage_root = storage_root
    if isinstance(app.state.diagnostics, dict):
        app.state.diagnostics["enabled"] = True

    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names.index("RateLimitMiddleware") < names.index("IdempotencyMiddleware") < names.index("AuthMiddleware"), names

    secret = (normalize_token(service_token) or "import-to-sabt-download").encode("utf-8")
    now_ts = int(clock.now().timestamp())
    token_payload = DownloadTokenPayload(
        namespace=namespace,
        filename=file_name,
        sha256=digest,
        size=len(content),
        exp=now_ts + 600,
        version="v1",
        created_at="2024-01-01T00:00:00+00:00",
    )
    token = encode_download_token(token_payload, secret=secret)

    with TestClient(app) as client:
        headers = {
            "Authorization": f"Bearer {service_token}",
            "X-Client-ID": f"client-{unique}",
            "X-Request-ID": f"req-{unique}",
        }
        response = client.get(f"/download/{token}", headers=headers)
        assert response.status_code == 200, response.text
        diagnostics = app.state.diagnostics
        assert diagnostics["last_chain"] == ["RateLimit", "Idempotency", "Auth"], diagnostics
