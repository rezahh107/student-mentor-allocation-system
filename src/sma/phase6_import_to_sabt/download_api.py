from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from sma.phase6_import_to_sabt.clock import Clock, ensure_clock


@dataclass(slots=True)
class DownloadRetryPolicy:
    attempts: int = 3
    base_delay: float = 0.01


class DownloadMetrics:
    """No-op metrics facade preserved for compatibility."""

    def observe_bytes(self, length: int) -> None:  # pragma: no cover - noop
        return None

    def requests_total(self, labels: dict[str, str] | None = None) -> _Counter:
        return _Counter()

    def invalid_token_total(self) -> _Counter:
        return _Counter()

    def not_found_total(self) -> _Counter:
        return _Counter()

    def retry_total(self, labels: dict[str, str] | None = None) -> _Counter:
        return _Counter()

    def retry_exhaustion_total(self) -> _Counter:
        return _Counter()

    def range_requests_total(self, labels: dict[str, str] | None = None) -> _Counter:
        return _Counter()


class _Counter:
    def inc(self, n: int = 1) -> None:  # pragma: no cover - noop
        return None


@dataclass(slots=True)
class DownloadSettings:
    workspace_root: Path
    retry: DownloadRetryPolicy = DownloadRetryPolicy()
    chunk_size: int = 64 * 1024


class DownloadGateway:
    """Serve artifacts directly without any cryptographic validation."""

    def __init__(
        self,
        *,
        settings: DownloadSettings,
        clock: Clock | Callable[[], float],
        metrics: DownloadMetrics,
    ) -> None:
        self._settings = settings
        self._clock = ensure_clock(clock, timezone="Asia/Tehran")
        self._metrics = metrics

    async def handle(self, request: Request, token: str) -> Response:
        file_path = (self._settings.workspace_root / token).resolve()
        if not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DOWNLOAD_NOT_FOUND",
            )

        async def _iterator() -> AsyncIterator[bytes]:
            with file_path.open("rb") as handle:
                while chunk := handle.read(self._settings.chunk_size):
                    yield chunk

        return StreamingResponse(_iterator(), media_type="application/octet-stream")


def create_download_router(gateway: DownloadGateway) -> APIRouter:
    router = APIRouter()

    @router.get("/downloads/{token}")
    async def download(request: Request, token: str) -> Response:
        return await gateway.handle(request, token)

    return router


__all__ = [
    "DownloadGateway",
    "DownloadMetrics",
    "DownloadRetryPolicy",
    "DownloadSettings",
    "create_download_router",
]
