from __future__ import annotations

import base64
import datetime as dt
import time
from typing import Callable, Iterator, Tuple
from uuid import uuid4

import pytest
import warnings

from fastapi.testclient import TestClient

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics


def _retry(action: Callable[[], None], *, attempts: int = 3, base_delay: float = 0.0005) -> None:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            action()
            return
        except AssertionError as exc:
            errors.append(str(exc))
            if attempt == attempts:
                raise AssertionError("; ".join(errors))
            delay = base_delay * (2 ** (attempt - 1)) + (attempt * 0.0001)
            time.sleep(delay)


@pytest.fixture
def api_client(tmp_path) -> Iterator[Tuple[TestClient, str, str]]:
    metrics_token = f"metrics-{uuid4().hex}"
    service_token = f"service-{uuid4().hex}"
    namespace = f"test:{uuid4().hex}"
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": namespace, "operation_timeout": 0.2},
        database={"dsn": "postgresql+asyncpg://localhost/test"},
        auth={
            "metrics_token": metrics_token,
            "service_token": service_token,
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )
    instant = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    clock = FixedClock(instant=instant)
    metrics = build_metrics("test_phase6_metrics")
    timer = DeterministicTimer()
    store_namespace = f"{namespace}:stores"
    rate_limit_store = InMemoryKeyValueStore(f"{store_namespace}:rl", clock)
    idempotency_store = InMemoryKeyValueStore(f"{store_namespace}:id", clock)
    app = create_application(
        config=config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_limit_store,
        idempotency_store=idempotency_store,
        readiness_probes={},
    )
    app.state.storage_root = tmp_path
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The 'app' shortcut is now deprecated.",
            category=DeprecationWarning,
        )
        with TestClient(app) as client:
            yield client, metrics_token, service_token


def test_download_invalid_signature_returns_persian_error(api_client) -> None:
    client, _metrics_token, _service_token = api_client
    signed_path = base64.urlsafe_b64encode("exports/sample.xlsx".encode("utf-8")).decode("utf-8").rstrip("=")
    params = {"signed": signed_path, "kid": "legacy", "exp": int(time.time()) + 600, "sig": "invalid"}
    response = client.get("/download", params=params)
    payload = response.json()
    assert response.status_code == 403, payload
    assert payload["fa_error_envelope"]["code"] == "DOWNLOAD_FORBIDDEN", payload
    assert payload["fa_error_envelope"]["message"] == "توکن نامعتبر است.", payload


def test_metrics_endpoint_requires_token(api_client) -> None:
    client, metrics_token, _service_token = api_client
    forbidden = client.get("/metrics")
    payload = forbidden.json()
    assert forbidden.status_code in {401, 403}, payload
    assert payload["fa_error_envelope"]["code"] == "UNAUTHORIZED", payload
    assert payload["fa_error_envelope"]["message"] == "توکن نامعتبر است.", payload

    def _assert_authorized() -> None:
        allowed = client.get("/metrics", headers={"X-Metrics-Token": metrics_token})
        assert allowed.status_code == 200, allowed.text
        assert allowed.text.startswith("#"), allowed.text

    _retry(_assert_authorized)
