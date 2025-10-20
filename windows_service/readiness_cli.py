"""CLI entry point for dependency readiness verification."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Sequence

from prometheus_client import CollectorRegistry, Counter, REGISTRY

from sma.core.clock import tehran_clock
from sma.infrastructure.monitoring.logging_adapter import (
    configure_json_logging,
    correlation_id_var,
)
from sma.phase6_import_to_sabt.sanitization import secure_digest
from windows_service.errors import DependencyNotReady, ServiceError
from windows_service.normalization import sanitize_env_text
from windows_service.readiness import plan_backoff, probe_dependencies

LOGGER = logging.getLogger(__name__)
_BACKOFF_CACHE: dict[int, Counter] = {}


def _backoff_counter(registry: CollectorRegistry) -> Counter:
    cache_key = id(registry)
    cached = _BACKOFF_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        counter = Counter(
            "winsw_readiness_backoff_total",
            "Backoff events emitted by the WinSW readiness CLI.",
            labelnames=("outcome",),
            registry=registry,
        )
    except ValueError:
        existing = registry._names_to_collectors.get("winsw_readiness_backoff_total")  # type: ignore[attr-defined]
        if isinstance(existing, Counter):
            counter = existing
        else:  # pragma: no cover - defensive
            raise
    _BACKOFF_CACHE[cache_key] = counter
    return counter


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate external dependencies for WinSW startup.")
    parser.add_argument("--check", action="store_true", help="Run readiness checks once with retries.")
    parser.add_argument("--attempts", type=int, default=3, help="Maximum number of readiness attempts.")
    parser.add_argument(
        "--base-delay-ms",
        type=int,
        default=150,
        help="Base backoff in milliseconds for readiness retries.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.5,
        help="Per attempt timeout in seconds when probing dependencies.",
    )
    return parser.parse_args(argv)


def _env_or_default(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return sanitize_env_text(value)


def _configure_logging() -> None:
    clock = tehran_clock()
    configure_json_logging(clock=clock)


def run_check(attempts: int, base_delay_ms: int, timeout: float, *, registry: CollectorRegistry | None = None) -> dict:
    dsn = _env_or_default("DATABASE_URL")
    redis_url = _env_or_default("REDIS_URL")
    if not dsn:
        raise ServiceError(
            "CONFIG_MISSING",
            "پیکربندی ناقص است؛ متغیر DATABASE_URL خالی است.",
            context={"variable": "DATABASE_URL"},
        )
    if not redis_url:
        raise ServiceError(
            "CONFIG_MISSING",
            "پیکربندی ناقص است؛ متغیر REDIS_URL خالی است.",
            context={"variable": "REDIS_URL"},
        )

    registry = registry or REGISTRY
    backoff_counter = _backoff_counter(registry)

    plan = plan_backoff("winsw-readiness", attempts, base_delay_ms)
    if not plan:
        plan = [base_delay_ms]
    results: dict | None = None
    last_error: ServiceError | None = None
    correlation = correlation_id_var.get()
    token = None
    if not correlation:
        correlation = secure_digest("winsw-readiness")
        token = correlation_id_var.set(correlation)
    try:
        for attempt_index in range(attempts):
            try:
                results = probe_dependencies(dsn, redis_url, timeout, registry=registry)
            except DependencyNotReady as exc:
                last_error = exc
                LOGGER.warning(
                    "readiness_retry", extra={"attempt": attempt_index + 1, "context": json.dumps(exc.context, ensure_ascii=False)}
                )
                if attempt_index == attempts - 1:
                    backoff_counter.labels(outcome="exhausted").inc()
                    raise
                delay_ms = plan[min(attempt_index, len(plan) - 1)]
                backoff_counter.labels(outcome="retry").inc()
                time.sleep(delay_ms / 1000.0)
                continue
            except ServiceError as exc:
                last_error = exc
                LOGGER.error(
                    "readiness_configuration_error",
                    extra={"context": json.dumps(exc.context, ensure_ascii=False)},
                )
                raise
            else:
                LOGGER.info(
                    "readiness_success",
                    extra={
                        "attempt": attempt_index + 1,
                        "results": json.dumps(results, ensure_ascii=False),
                    },
                )
                backoff_counter.labels(outcome="success").inc()
                return results
        assert last_error is not None
        raise last_error
    finally:
        if token is not None:
            correlation_id_var.reset(token)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.check:
        return 0
    _configure_logging()
    registry = CollectorRegistry()
    try:
        run_check(args.attempts, args.base_delay_ms, args.timeout, registry=registry)
    except ServiceError as exc:
        message = exc.message if isinstance(exc, ServiceError) else str(exc)
        envelope = {
            "fa_error_envelope": {
                "code": exc.code if isinstance(exc, ServiceError) else "READINESS_FAILED",
                "message": message,
                "context": dict(exc.context) if isinstance(exc, ServiceError) else {},
            }
        }
        LOGGER.error("readiness_failed", extra={"detail": json.dumps(envelope, ensure_ascii=False)})
        sys.stderr.write(json.dumps(envelope, ensure_ascii=False) + "\n")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI execution
    raise SystemExit(main())
