from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import pytest
from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics

from tests.rbac.test_admin_vs_manager import SyncASGIClient


@pytest.fixture
def download_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[SyncASGIClient]:
    unique = uuid4().hex
    redis_ns = f"import_to_sabt_download_{unique}"
    service_secret = f"svc-{unique}"
    metrics_token = f"metrics-{unique}"
    signing_payload = [
        {"kid": "active", "secret": f"secret-{unique}", "state": "active"},
    ]
    monkeypatch.setenv("TOKENS", json.dumps([]))
    monkeypatch.setenv("DOWNLOAD_SIGNING_KEYS", json.dumps(signing_payload))
    monkeypatch.setenv("EXPORT_STORAGE_DIR", str(tmp_path))
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": redis_ns},
        database={"dsn": "postgresql://example/example"},
        auth={
            "metrics_token": metrics_token,
            "service_token": service_secret,
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )
    clock = FixedClock(instant=datetime(2024, 1, 1, tzinfo=timezone.utc))
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_download_{unique}")
    rate_store = InMemoryKeyValueStore(f"{redis_ns}:rate", clock)
    idem_store = InMemoryKeyValueStore(f"{redis_ns}:idem", clock)
    app = create_application(
        config=config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    try:
        with SyncASGIClient(app) as client:
            yield client
    finally:
        rate_store._store.clear()
        idem_store._store.clear()


def _make_artifact(root: Path, relative: str, content: bytes) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_signed_download_happy_path(download_client: SyncASGIClient, tmp_path: Path) -> None:
    storage = Path(download_client.app.state.storage_root)
    _make_artifact(storage, "exports/report.csv", b"id,name\r\n1,Ali\r\n")
    signer = download_client.app.state.download_signer
    components = signer.issue("exports/report.csv", ttl_seconds=120)
    response = download_client.get(
        f"/downloads/{components.token_id}",
        params=components.as_query(),
    )
    assert response.status_code == 200
    assert response.content.startswith(b"id,name")


def test_signed_download_rejects_expired(download_client: SyncASGIClient, tmp_path: Path) -> None:
    storage = Path(download_client.app.state.storage_root)
    _make_artifact(storage, "exports/expired.csv", b"x,y\r\n1,2\r\n")
    signer = download_client.app.state.download_signer
    components = signer.issue("exports/expired.csv", ttl_seconds=1)
    params = components.as_query()
    params["expires"] = str(int(params["expires"]) - 3600)
    response = download_client.get(f"/downloads/{components.token_id}", params=params)
    assert response.status_code == 403
    payload = response.json()
    assert payload["fa_error_envelope"]["message"] == "پیوند دانلود نامعتبر/منقضی است."


def test_signed_download_rejects_tampered_signature(download_client: SyncASGIClient, tmp_path: Path) -> None:
    storage = Path(download_client.app.state.storage_root)
    _make_artifact(storage, "exports/tampered.csv", b"a,b\r\n3,4\r\n")
    signer = download_client.app.state.download_signer
    components = signer.issue("exports/tampered.csv", ttl_seconds=120)
    params = components.as_query()
    params["signature"] = "0" * len(params["signature"])
    response = download_client.get(f"/downloads/{components.token_id}", params=params)
    assert response.status_code == 403
    payload = response.json()
    assert payload["fa_error_envelope"]["message"] == "پیوند دانلود نامعتبر/منقضی است."

