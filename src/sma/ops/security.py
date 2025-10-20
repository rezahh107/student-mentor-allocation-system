from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import OpsSettings


def require_metrics_token(settings: OpsSettings, token: str | None) -> None:
    if token != settings.metrics_read_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="دسترسی مجاز نیست")


async def metrics_guard(
    settings: OpsSettings,
    metrics_read_token: str | None = Header(default=None, alias="X-Metrics-Token"),
) -> None:
    require_metrics_token(settings, metrics_read_token)


__all__ = ["metrics_guard", "require_metrics_token"]
