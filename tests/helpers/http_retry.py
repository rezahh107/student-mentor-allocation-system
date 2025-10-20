"""Deterministic ASGI retry helpers for integration tests."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import Iterable, Mapping, MutableMapping, Sequence

import httpx

from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics
from sma.phase6_import_to_sabt.sanitization import sanitize_text

_ALLOWED_DEBUG_HEADERS = {"retry-after", "x-request-id", "x-ratelimit-remaining"}


@dataclass(slots=True)
class RetryAttempt:
    attempt: int
    status_code: int | None
    delay_seconds: float
    headers: dict[str, str]
    error: str | None
    message: str | None


@dataclass(slots=True)
class RetryContext:
    operation: str
    route: str
    namespace: str
    jitter_seed: str
    attempts: list[RetryAttempt] = field(default_factory=list)
    last_error: str | None = None

    def add_attempt(self, attempt: RetryAttempt) -> None:
        self.attempts.append(attempt)
        if attempt.error:
            self.last_error = attempt.error
        elif attempt.status_code and attempt.status_code >= 400:
            self.last_error = f"status:{attempt.status_code}"

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "route": self.route,
            "namespace": self.namespace,
            "jitter_seed": self.jitter_seed,
            "attempts": [attempt.__dict__ for attempt in self.attempts],
            "last_error": self.last_error,
        }


class RetryExhaustedError(RuntimeError):
    """Raised when deterministic retries fail to achieve a successful response."""

    def __init__(self, context: RetryContext) -> None:
        super().__init__(
            sanitize_text(
                f"retry_exhausted:op={context.operation}:route={context.route}:attempts={len(context.attempts)}"
            )
        )
        self.context = context


def _safe_headers(headers: Mapping[str, str | Sequence[str]]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key in _ALLOWED_DEBUG_HEADERS:
        value = headers.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0]
        safe[key] = sanitize_text(str(value))
    return safe


def _safe_excerpt(response: httpx.Response, *, limit: int = 160) -> str | None:
    if not response.content:
        return None
    preview = response.text[:limit]
    sanitized = sanitize_text(preview)
    return sanitized or None


def _compute_delay(base_delay: float, attempt: int, seed: str) -> float:
    raw = f"{seed}:{attempt}".encode("utf-8")
    digest = blake2b(raw, digest_size=8).digest()
    jitter = int.from_bytes(digest, "big") / float(1 << 64)
    # Keep jitter bounded within ±20% of the exponential backoff step.
    return base_delay * (2 ** (attempt - 1)) * (0.9 + 0.2 * jitter)


def _increment_attempt_metric(
    metrics: ServiceMetrics | None, operation: str, route: str, *, exhausted: bool
) -> None:
    if metrics is None:
        return
    metrics.retry_attempts_total.labels(operation=operation, route=route).inc()
    if exhausted:
        metrics.retry_exhausted_total.labels(operation=operation, route=route).inc()


async def asgi_request_with_retry(
    app,
    method: str,
    path: str,
    *,
    headers: MutableMapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    json: object | None = None,
    data: object | None = None,
    max_attempts: int = 3,
    base_delay: float = 0.05,
    jitter_seed: str | None = None,
    namespace: str = "tests",
    operation: str = "http.request",
    retry_statuses: Iterable[int] = (429, 503),
    allowed_statuses: Iterable[int] | None = None,
    retry_exceptions: tuple[type[Exception], ...] = (httpx.HTTPError,),
    metrics: ServiceMetrics | None = None,
) -> tuple[httpx.Response, RetryContext]:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    retry_codes = {int(code) for code in retry_statuses}
    ok_codes = {int(code) for code in allowed_statuses} if allowed_statuses is not None else None
    jitter_seed = jitter_seed or f"{namespace}:{operation}:{path}"
    context = RetryContext(
        operation=operation,
        route=path,
        namespace=namespace,
        jitter_seed=jitter_seed,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        attempt = 1
        while attempt <= max_attempts:
            delay = _compute_delay(base_delay, attempt, jitter_seed)
            if metrics is not None:
                metrics.retry_backoff_seconds.labels(operation=operation, route=path).observe(delay)
            _increment_attempt_metric(metrics, operation, path, exhausted=False)
            try:
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                )
            except retry_exceptions as exc:  # pragma: no cover - network style issues
                sanitized = sanitize_text(str(exc))
                context.add_attempt(
                    RetryAttempt(
                        attempt=attempt,
                        status_code=None,
                        delay_seconds=delay,
                        headers={},
                        error=f"exception:{sanitized}",
                        message=None,
                    )
                )
                if attempt == max_attempts:
                    _increment_attempt_metric(metrics, operation, path, exhausted=True)
                    raise RetryExhaustedError(context) from exc
                attempt += 1
                await asyncio.sleep(0)
                continue

            status = response.status_code
            headers_snapshot = _safe_headers(response.headers)
            excerpt = _safe_excerpt(response)
            should_retry = status in retry_codes or (status >= 500 and (ok_codes is None or status not in ok_codes))
            attempt_record = RetryAttempt(
                attempt=attempt,
                status_code=status,
                delay_seconds=delay,
                headers=headers_snapshot,
                error=f"status:{status}" if should_retry else None,
                message=excerpt,
            )
            context.add_attempt(attempt_record)
            if should_retry and attempt < max_attempts:
                attempt += 1
                await asyncio.sleep(0)
                continue
            if should_retry:
                _increment_attempt_metric(metrics, operation, path, exhausted=True)
                raise RetryExhaustedError(context)
            return response, context
    _increment_attempt_metric(metrics, operation, path, exhausted=True)
    raise RetryExhaustedError(context)


def request_with_retry(*args, **kwargs) -> tuple[httpx.Response, RetryContext]:
    """Sync wrapper for :func:`asgi_request_with_retry`."""

    return asyncio.run(asgi_request_with_retry(*args, **kwargs))


__all__ = [
    "RetryAttempt",
    "RetryContext",
    "RetryExhaustedError",
    "asgi_request_with_retry",
    "request_with_retry",
]
