from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol, Sequence
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


@dataclass(frozen=True)
class ExportManifestSummary:
    """Minimal manifest summary for SSR tables."""

    name: str
    size_bytes: int
    created_at: datetime
    token: str


class ExportManifestRepository(Protocol):
    """Protocol describing a read-only manifest store."""

    def list_recent(self, limit: int = 20) -> Sequence[ExportManifestSummary]:
        ...


class SignedURLProvider(Protocol):
    """Protocol for building deterministic signed download URLs."""

    def build(self, token: str) -> str:
        ...


def _default_repository() -> ExportManifestRepository:
    raise RuntimeError("Repository dependency must be provided")


def _default_signed_provider() -> SignedURLProvider:
    raise RuntimeError("Signed URL provider dependency must be provided")


def build_router(
    *,
    templates: Jinja2Templates,
    repository: ExportManifestRepository = Depends(_default_repository),
    signer: SignedURLProvider = Depends(_default_signed_provider),
) -> APIRouter:
    router = APIRouter()

    def _render(
        request: Request,
        manifests: Iterable[ExportManifestSummary],
        *,
        partial: bool,
    ) -> HTMLResponse:
        tehran = ZoneInfo("Asia/Tehran")
        enriched = [
            {
                "name": item.name,
                "size_bytes": item.size_bytes,
                "token": item.token,
                "created_at": item.created_at,
                "display_created_at": item.created_at.astimezone(tehran).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for item in manifests
        ]
        context = {
            "request": request,
            "manifests": enriched,
            "partial": partial,
            "hx_rows_url": request.url_for("exports_ui_rows"),
        }
        return templates.TemplateResponse("exports/index.html", context)

    @router.get("/ui/exports", response_class=HTMLResponse, name="exports_ui_index")
    async def exports_page(request: Request, repo: ExportManifestRepository = Depends(lambda: repository)) -> HTMLResponse:
        manifests = repo.list_recent(limit=25)
        return _render(request, manifests, partial=False)

    @router.get("/ui/exports/rows", response_class=HTMLResponse, name="exports_ui_rows")
    async def exports_rows(request: Request, repo: ExportManifestRepository = Depends(lambda: repository)) -> HTMLResponse:
        manifests = repo.list_recent(limit=25)
        return _render(request, manifests, partial=True)

    @router.get(
        "/ui/exports/{token}/signed-url",
        response_class=HTMLResponse,
        name="exports_ui_signed_url",
    )
    async def exports_signed_url(token: str, provider: SignedURLProvider = Depends(lambda: signer)) -> HTMLResponse:
        url = provider.build(token)
        safe_url = html.escape(url)
        safe_token = html.escape(token)
        snippet = f"<span class=\"hx-signed-url\" data-token=\"{safe_token}\">{safe_url}</span>"
        return HTMLResponse(snippet)

    return router


__all__ = [
    "ExportManifestRepository",
    "ExportManifestSummary",
    "SignedURLProvider",
    "build_router",
]
