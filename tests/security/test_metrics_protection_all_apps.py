import asyncio
import json
from hashlib import blake2s
from typing import Any, Dict

import httpx

from sma.infrastructure.api.routes import create_app as create_infra_app
from tests.mw.test_middleware_order_all_apps import _build_phase6_app

_ANCHOR = "AGENTS.md::Observability & No PII"
_HTTP_OK = 200


def _send_request(app, method: str, path: str, **kwargs):
    async def _call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_call())


def test_metrics_endpoint_is_public_phase6(monkeypatch) -> None:
    app = _build_phase6_app(monkeypatch)
    response = _send_request(app, "GET", "/metrics")
    context: Dict[str, Any] = {
        "evidence": _ANCHOR,
        "status": response.status_code,
        "headers": dict(response.headers),
    }
    assert response.status_code == _HTTP_OK, json.dumps(context, ensure_ascii=False)


def test_metrics_endpoint_is_public_infrastructure(monkeypatch) -> None:
    digest = blake2s(b"infra-metrics", digest_size=6).hexdigest()
    token = f"infra-{digest}"
    monkeypatch.setenv("METRICS_TOKEN", token)
    app = create_infra_app()

    response = _send_request(app, "GET", "/metrics")
    context = {
        "evidence": _ANCHOR,
        "status": response.status_code,
        "headers": dict(response.headers),
    }
    assert response.status_code == _HTTP_OK, json.dumps(context, ensure_ascii=False)
