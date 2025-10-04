from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from zoneinfo import ZoneInfo

from src.web.routes.exports_ui import (
    ExportManifestRepository,
    ExportManifestSummary,
    SignedURLProvider,
    build_router,
)


class _ChainMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, name: str) -> None:
        super().__init__(app)
        self._name = name

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        chain = getattr(request.state, "middleware_chain", [])
        request.state.middleware_chain = chain + [self._name]
        response = await call_next(request)
        response.headers["X-Middleware-Chain"] = ",".join(request.state.middleware_chain)
        return response


class _StubRepository(ExportManifestRepository):
    def __init__(self, items: List[ExportManifestSummary]):
        self._items = items

    def list_recent(self, limit: int = 20):  # type: ignore[override]
        return self._items[:limit]


class _StubSigner(SignedURLProvider):
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def build(self, token: str) -> str:  # type: ignore[override]
        return f"{self._prefix}/{token}"


@pytest.mark.ui
def test_ssr_hx_exports_list_and_signed_url() -> None:
    """AGENTS.md::UI & Observability — SSR list renders with HTMX and preserves middleware order."""

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "src" / "web" / "templates"))
    created_at = datetime(2024, 1, 5, 9, 30, tzinfo=ZoneInfo("Asia/Tehran"))
    manifests = [
        ExportManifestSummary(
            name="export_SABT_V1_1402-ALL_20240105093000_001.xlsx",
            size_bytes=153600,
            created_at=created_at,
            token="token-001",
        ),
        ExportManifestSummary(
            name="export_SABT_V1_1402-ALL_20240105093000_002.csv",
            size_bytes=51200,
            created_at=created_at,
            token="token-002",
        ),
    ]
    repository = _StubRepository(manifests)
    signer = _StubSigner("https://signed.test")

    app = FastAPI(
        middleware=[
            Middleware(_ChainMiddleware, name="RateLimit"),
            Middleware(_ChainMiddleware, name="Idempotency"),
            Middleware(_ChainMiddleware, name="Auth"),
        ]
    )
    app.include_router(build_router(templates=templates, repository=repository, signer=signer))

    with TestClient(app) as client:
        response = client.get("/ui/exports")
        assert response.status_code == 200, response.text
        chain = response.headers.get("X-Middleware-Chain", "")
        assert chain.split(",") == ["RateLimit", "Idempotency", "Auth"]
        body = response.text
        assert "فهرست خروجی‌های اخیر SABT" in body
        assert "/ui/exports/rows" in body
        assert "دریافت لینک امضا شده" in body

        hx_response = client.get("/ui/exports/rows", headers={"HX-Request": "true"})
        assert hx_response.status_code == 200
        assert hx_response.text.count("data-testid=\"export-row\"") == len(manifests)

        signed_response = client.get("/ui/exports/token-001/signed-url")
        assert signed_response.status_code == 200
        assert "https://signed.test/token-001" in signed_response.text
