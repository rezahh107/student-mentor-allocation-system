from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def install_error_handlers(app) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "fa_error_envelope": {
                    "code": getattr(exc, "code", "HTTP_ERROR"),
                    "message": "درخواست با خطای مشخص روبرو شد.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "fa_error_envelope": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "مشکل داخلی سیستم رخ داده است.",
                }
            },
        )


__all__ = ["install_error_handlers"]
