from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Iterator
from uuid import uuid4

import httpx
import pytest

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics

from tests.helpers.jwt_factory import build_jwt


class SyncASGIClient:
    def __init__(self, app) -> None:
        self.app = app
        self._transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(transport=self._transport, base_url="http://testserver")

    def _run(self, coro):
        return asyncio.run(coro)

    def get(self, url: str, **kwargs):
        return self._run(self._client.get(url, **kwargs))

    def post(self, url: str, **kwargs):
        return self._run(self._client.post(url, **kwargs))

    def close(self) -> None:
        self._run(self._client.aclose())
        self._run(self._transport.aclose())

    def __enter__(self) -> SyncASGIClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - protocol signature
        self.close()


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[SyncASGIClient, dict[str, str]]]:
    unique = uuid4().hex
    redis_ns = f"import_to_sabt_rbac_{unique}"
    metrics_ns = f"import_to_sabt_metrics_{unique}"
    service_secret = f"service-secret-{unique}"
    metrics_token = f"metrics-token-{unique}"
    tokens_payload: list[dict[str, object]] = [
        {"value": metrics_token, "role": "METRICS_RO", "metrics": True},
    ]
    signing_payload = [
        {"kid": "active", "secret": f"secret-{unique}", "state": "active"},
    ]
    monkeypatch.setenv("TOKENS", json.dumps(tokens_payload))
    monkeypatch.setenv("DOWNLOAD_SIGNING_KEYS", json.dumps(signing_payload))
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": redis_ns},
        database={"dsn": "postgresql://test/test"},
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
    metrics = build_metrics(metrics_ns)
    rate_store = InMemoryKeyValueStore(f"{redis_ns}:rate", clock)
    idem_store = InMemoryKeyValueStore(f"{redis_ns}:idem", clock)
    rate_store._store.clear()
    idem_store._store.clear()
    app = create_application(
        config=config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    creds = {
        "service_secret": service_secret,
        "metrics_token": metrics_token,
        "now_ts": int(clock.now().timestamp()),
    }
    try:
        with SyncASGIClient(app) as client:
            yield client, creds
    finally:
        rate_store._store.clear()
        idem_store._store.clear()


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_access_any_center(api_client: tuple[SyncASGIClient, dict[str, str]]) -> None:
    client, creds = api_client
    token = build_jwt(
        secret=creds["service_secret"],
        subject="admin-1",
        role="ADMIN",
        center=None,
        iat=creds["now_ts"],
        exp=creds["now_ts"] + 3600,
    )
    response = client.get("/api/jobs", headers=_auth_header(token), params={"center": "987"})
    body = response.json()
    assert response.status_code == 200, body
    assert body["role"] == "ADMIN"
    assert body["center"] == 987


def test_manager_limited_to_scope(api_client: tuple[SyncASGIClient, dict[str, str]]) -> None:
    client, creds = api_client
    manager_token = build_jwt(
        secret=creds["service_secret"],
        subject="manager-1",
        role="MANAGER",
        center=777,
        iat=creds["now_ts"],
        exp=creds["now_ts"] + 3600,
    )

    ok_response = client.get("/api/jobs", headers=_auth_header(manager_token), params={"center": "777"})
    ok_body = ok_response.json()
    assert ok_response.status_code == 200, ok_body
    assert ok_body["center"] == 777

    denied = client.get("/api/jobs", headers=_auth_header(manager_token), params={"center": "100"})
    assert denied.status_code == 403, denied.text
    payload = denied.json()
    assert payload["fa_error_envelope"]["message"] == "دسترسی مجاز نیست؛ نقش/حوزهٔ شما این عملیات را پشتیبانی نمی‌کند."


def test_manager_job_creation_forces_scope(api_client: tuple[SyncASGIClient, dict[str, str]]) -> None:
    client, creds = api_client
    token = build_jwt(
        secret=creds["service_secret"],
        subject="manager-2",
        role="MANAGER",
        center=321,
        iat=creds["now_ts"],
        exp=creds["now_ts"] + 3600,
    )
    body = {"center": 999}
    headers = _auth_header(token)
    headers["Idempotency-Key"] = "manager-create-321"
    response = client.post("/api/jobs", headers=headers, json=body)
    payload = response.json()
    assert response.status_code == 200, payload
    assert payload["center"] == 321

