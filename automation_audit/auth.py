from __future__ import annotations

from typing import Iterable, Optional

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class AuthConfig:
    def __init__(self, tokens: Iterable[str], *, ip_allowlist: Optional[Iterable[str]] = None) -> None:
        self.tokens = {token for token in tokens if token}
        self.ip_allowlist = {ip for ip in ip_allowlist or []}

    def is_allowed(self, request: Request) -> bool:
        client_host = request.client.host if request.client else None
        if self.ip_allowlist and client_host not in self.ip_allowlist:
            return False
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1]
            return token in self.tokens
        return False


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: AuthConfig):
        super().__init__(app)
        self.config = config

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - integration tested
        if not self.config.is_allowed(request):
            return JSONResponse({"detail": "دسترسی مجاز نیست."}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)
