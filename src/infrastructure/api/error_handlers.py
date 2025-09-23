# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.domain.shared.errors import AllocationError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AllocationError)
    async def handle_alloc_error(request: Request, exc: AllocationError):  # type: ignore[unused-ignore]
        return JSONResponse(status_code=400, content={"error": exc.error_code, "message": exc.message})

