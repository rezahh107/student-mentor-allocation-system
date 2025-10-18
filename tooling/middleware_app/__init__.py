from __future__ import annotations

"""FastAPI application exposing RateLimit → Idempotency → Auth middlewares."""

import json
import os

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..domain import AcademicYearProvider, ValidationError, validate_registration
from ..logging_utils import get_json_logger
from ..metrics import get_registry

RATE_LIMIT_ERROR = "درخواست زیاد است؛ لطفاً بعداً تلاش کنید."
AUTH_ERROR = "دسترسی غیرمجاز است."
IDEMPOTENCY_ERROR = "شناسه تکراری است."  # deterministic


@dataclass
class RedisNamespace:
    client: Any
    namespace: str

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def incr(self, key: str, ttl_seconds: int) -> int:
        namespaced = self._key(key)
        count = self.client.incr(namespaced)
        self.client.expire(namespaced, ttl_seconds)
        return int(count)

    def get(self, key: str) -> str | None:
        value = self.client.get(self._key(key))
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.client.set(self._key(key), value, ex=ttl_seconds)

    def delete_prefix(self) -> None:
        for key in list(self.client.scan_iter(match=f"{self.namespace}:*")):
            self.client.delete(key)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, redis: RedisNamespace) -> None:
        super().__init__(app)
        self.redis = redis

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        request.state.middleware_order = getattr(request.state, "middleware_order", [])
        request.state.middleware_order.append("rate-limit")
        rid = request.headers.get("X-Request-ID", "global")
        count = self.redis.incr(f"rl:{rid}", ttl_seconds=1)
        if count > 5:
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, redis: RedisNamespace, ttl_hours: int = 24) -> None:
        super().__init__(app)
        self.redis = redis
        self.ttl = ttl_hours * 3600

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        request.state.middleware_order = getattr(request.state, "middleware_order", [])
        request.state.middleware_order.append("idempotency")
        if request.method in {"POST", "PUT"}:
            key = request.headers.get("X-Idempotency-Key")
            if not key:
                return JSONResponse({"error": IDEMPOTENCY_ERROR}, status_code=status.HTTP_400_BAD_REQUEST)
            cached = self.redis.get(f"idem:{key}")
            if cached:
                payload = json.loads(cached)
                return JSONResponse(
                    payload["body"],
                    headers=payload["headers"],
                    status_code=payload["status"],
                )
            response: Response = await call_next(request)
            if hasattr(response, "body_iterator"):
                chunks = []
                async for chunk in response.body_iterator:
                    if isinstance(chunk, bytes):
                        chunks.append(chunk)
                    else:
                        chunks.append(str(chunk).encode())
                raw_body = b"".join(chunks)
            else:
                raw = getattr(response, "body", b"")
                raw_body = raw if isinstance(raw, bytes) else str(raw or "").encode()
            try:
                parsed = json.loads(raw_body.decode() or "{}")
            except json.JSONDecodeError:
                parsed = {"raw": raw_body.decode(errors="ignore")}
            payload = {
                "body": parsed,
                "headers": dict(response.headers),
                "status": response.status_code,
            }
            self.redis.set(
                f"idem:{key}", json.dumps(payload, ensure_ascii=False), ttl_seconds=self.ttl
            )
            return JSONResponse(
                payload["body"],
                headers=payload["headers"],
                status_code=payload["status"],
            )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        request.state.middleware_order = getattr(request.state, "middleware_order", [])
        request.state.middleware_order.append("auth")
        if request.url.path == "/metrics":
            return await call_next(request)
        header = request.headers.get("Authorization")
        if header != f"Bearer {self.token}":
            return JSONResponse({"error": AUTH_ERROR}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)


def get_app(redis_client: Any, namespace: str, token: str = "secret-token") -> FastAPI:
    redis = RedisNamespace(redis_client, namespace)
    app = FastAPI()
    app.add_middleware(AuthMiddleware, token=token)
    app.add_middleware(IdempotencyMiddleware, redis=redis)
    app.add_middleware(RateLimitMiddleware, redis=redis)

    logger = get_json_logger("middleware", correlation_id="test")
    provider = AcademicYearProvider({2024: "24"})

    @app.middleware("http")
    async def tracking_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:  # pragma: no cover
        response = await call_next(request)
        return response

    @app.post("/submit")
    async def submit(request: Request) -> Response:
        request.state.middleware_order.append("endpoint")
        payload = await request.json()
        try:
            validated = validate_registration(payload, provider)
        except ValidationError as exc:
            logger.info("validation-error", extra={"error": str(exc)})
            return JSONResponse({"error": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
        logger.info("accepted", extra={"fields": list(validated.keys())})
        body = {
            "status": "ok",
            "middleware_order": request.state.middleware_order,
            "student_type": validated["student_type"],
            "gender_prefix": validated["gender_prefix"],
            "year_code": validated["year_code"],
        }
        return JSONResponse(body)

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        token_value = request.headers.get("X-Metrics-Token")
        if token_value != token:
            return PlainTextResponse("", status_code=status.HTTP_403_FORBIDDEN)
        data = []
        for metric in get_registry().collect():
            for sample in metric.samples:
                labels = ",".join(f'{k}="{v}"' for k, v in sample.labels.items())
                data.append(f"{sample.name}{{{labels}}} {sample.value}")
        return PlainTextResponse("\n".join(data))

    return app


def get_debug_context(redis: RedisNamespace) -> dict[str, Any]:
    keys = list(redis.client.scan_iter(match=f"{redis.namespace}:*"))
    rate_limit_keys = {}
    for key in keys:
        value = redis.client.get(key)
        if value is None:
            continue
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        if ":rl:" in key_str:
            rate_limit_keys[key_str] = int(value)
    return {
        "redis_keys": keys,
        "namespace": redis.namespace,
        "rate_limit_state": rate_limit_keys,
        "env": os.getenv("GITHUB_ACTIONS", "local"),
    }
