from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from sma.core.clock import DEFAULT_TIMEZONE
from sma.phase6_import_to_sabt.security.config import SigningKeyDefinition
from sma.phase6_import_to_sabt.security.signer import (
    DualKeySigner,
    SignatureError,
    SigningKeySet,
)
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.infrastructure.api.routes import create_app


class _DeterministicClock:
    def __init__(self) -> None:
        self._now = datetime(2024, 1, 1, tzinfo=ZoneInfo(DEFAULT_TIMEZONE))

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@pytest.fixture(name="security_state")
def fixture_security_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    namespace = uuid4().hex
    token = f"metrics-{namespace}"
    monkeypatch.setenv("METRICS_TOKEN", token)
    monkeypatch.setenv("PYTHONPATH", os.fspath(os.path.abspath(".")))
    yield {"token": token, "namespace": namespace}


def _request_with_retry(client: TestClient, method: str, url: str, **kwargs) -> tuple[int, str]:
    base_delay = 0.05
    seed = uuid4().hex
    for attempt in range(1, 4):
        response = client.request(method, url, **kwargs)
        if response.status_code < 500:
            return response.status_code, response.text
        time.sleep(base_delay * attempt)
    raise AssertionError(
        json.dumps(
            {
                "url": url,
                "method": method,
                "attempts": attempt,
                "status": response.status_code,
                "body": response.text,
                "seed": seed,
            },
            ensure_ascii=False,
        )
    )


@pytest.mark.integration
@pytest.mark.timeout(30)
def test_metrics_token_guard(security_state: dict[str, str]) -> None:
    app = create_app()
    client = TestClient(app)

    forbidden_status, forbidden_body = _request_with_retry(client, "GET", "/metrics")
    assert forbidden_status in {401, 403}, forbidden_body

    ok_status, ok_body = _request_with_retry(
        client,
        "GET",
        "/metrics",
        headers={"X-Metrics-Token": security_state["token"]},
    )
    assert ok_status == 200, ok_body
    assert "HELP" in ok_body or "export_jobs_total" in ok_body


@pytest.mark.integration
@pytest.mark.timeout(30)
def test_signed_download_guard(security_state: dict[str, str]) -> None:
    registry = CollectorRegistry()
    metrics = build_import_export_metrics(registry)
    clock = _DeterministicClock()
    keys = SigningKeySet(
        [
            SigningKeyDefinition(
                kid=f"kid{security_state['namespace'][:4]}",
                secret=f"secret-{security_state['namespace']}",
                state="active",
            )
        ]
    )
    signer = DualKeySigner(keys=keys, clock=clock, metrics=metrics, default_ttl_seconds=60)

    components = signer.issue("/exports/demo.xlsx", ttl_seconds=60)

    app = FastAPI()

    @app.get("/download")
    def download_endpoint(signed: str, kid: str, exp: int, sig: str) -> dict[str, str]:
        try:
            path = signer.verify_components(signed=signed, kid=kid, exp=exp, sig=sig)
        except SignatureError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": exc.reason, "message": exc.message_fa},
            ) from exc
        return {"path": path}

    client = TestClient(app)

    bad_status, bad_body = _request_with_retry(
        client,
        "GET",
        "/download",
        params={**components.as_query(), "sig": "forged"},
    )
    assert bad_status == 403, bad_body
    assert "توکن نامعتبر" in bad_body

    clock.advance(120)
    expired_status, expired_body = _request_with_retry(
        client,
        "GET",
        "/download",
        params=components.as_query(),
    )
    assert expired_status == 403, expired_body
    assert "لینک دانلود منقضی" in expired_body

    clock.advance(-120)
    fresh_components = signer.issue("/exports/demo.xlsx", ttl_seconds=120)
    ok_status, ok_body = _request_with_retry(
        client,
        "GET",
        "/download",
        params=fresh_components.as_query(),
    )
    assert ok_status == 200, ok_body
    assert "/exports/demo.xlsx" in ok_body
