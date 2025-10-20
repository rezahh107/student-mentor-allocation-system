"""Deterministic cleanup helper for Windows CI runs."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

try:
    import hashlib
except Exception:  # pragma: no cover - fallback
    hashlib = None  # type: ignore

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

try:
    from sqlalchemy import create_engine, text  # type: ignore
except Exception:  # pragma: no cover
    create_engine = None  # type: ignore
    text = None  # type: ignore

try:
    from tenacity import retry, stop_after_attempt, wait_exponential_jitter
except Exception:  # pragma: no cover
    retry = None  # type: ignore
    stop_after_attempt = None  # type: ignore
    wait_exponential_jitter = None  # type: ignore


@dataclass
class CleanupResult:
    component: str
    status: str
    detail: str
    duration_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _hash_value(value: str) -> str:
    if not value:
        return ""
    if hashlib is None:
        return "***"
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()
    return f"blake2b16:{digest}"


def _log(message: str) -> None:
    sys.stdout.write(f"[clean-state] {message}\n")
    sys.stdout.flush()


def _with_retry(func):
    if retry is None or stop_after_attempt is None or wait_exponential_jitter is None:
        return func
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.1, max=1.5),
        reraise=True,
    )(func)


def _cleanup_redis(url: str, namespace: str) -> CleanupResult:
    start = _now_ms()
    if redis is None:
        return CleanupResult("redis", "skipped", "redis-py not installed", _now_ms() - start)

    @_with_retry
    def _flush() -> CleanupResult:
        client = redis.Redis.from_url(
            url,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=True,
        )
        client.ping()
        pattern = f"{namespace}:*" if namespace else "*"
        keys = client.keys(pattern)
        deleted = 0
        if keys:
            deleted = client.delete(*keys)
        client.close()
        return CleanupResult(
            "redis",
            "ok",
            f"deleted_keys={deleted}",
            _now_ms() - start,
        )

    try:
        return _flush()
    except Exception as exc:  # pragma: no cover - best effort only
        return CleanupResult("redis", "warning", f"{type(exc).__name__}: {exc}", _now_ms() - start)


def _cleanup_database(url: str) -> CleanupResult:
    start = _now_ms()
    if not url:
        return CleanupResult("database", "skipped", "DATABASE_URL not set", _now_ms() - start)
    if create_engine is None or text is None:
        return CleanupResult("database", "skipped", "SQLAlchemy unavailable", _now_ms() - start)

    @_with_retry
    def _connect() -> CleanupResult:
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=60)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.commit()
        engine.dispose()
        return CleanupResult("database", "ok", "connection_ok", _now_ms() - start)

    try:
        return _connect()
    except Exception as exc:  # pragma: no cover - best effort only
        return CleanupResult("database", "warning", f"{type(exc).__name__}: {exc}", _now_ms() - start)


def _cleanup_rate_limiter() -> CleanupResult:
    start = _now_ms()
    try:
        from sma.infrastructure.rate_limit import registry  # type: ignore
    except Exception:  # pragma: no cover - optional module
        return CleanupResult("rate_limiter", "skipped", "registry unavailable", _now_ms() - start)

    try:
        with registry.scoped_reset():  # type: ignore[attr-defined]
            pass
        return CleanupResult("rate_limiter", "ok", "scoped_reset", _now_ms() - start)
    except Exception as exc:  # pragma: no cover
        return CleanupResult("rate_limiter", "warning", f"{type(exc).__name__}: {exc}", _now_ms() - start)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CI state cleanup utility")
    parser.add_argument("--phase", choices=["pre", "post"], required=True)
    parser.add_argument("--namespace", default="", help="Unique namespace for Redis keys")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    namespace = args.namespace
    metadata: Dict[str, Any] = {
        "phase": args.phase,
        "namespace": namespace,
        "timestamp": int(time.time()),
        "env": {
            "GITHUB_ACTIONS": os.getenv("GITHUB_ACTIONS", "0"),
            "PYTEST_XDIST_WORKER": os.getenv("PYTEST_XDIST_WORKER", ""),
        },
    }

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    database_url = os.getenv("DATABASE_URL", "")
    metadata["redis_url_hash"] = _hash_value(redis_url)
    metadata["database_url_hash"] = _hash_value(database_url)

    _log(json.dumps({"event": "cleanup-start", **metadata}))

    results = [
        _cleanup_redis(redis_url, namespace),
        _cleanup_database(database_url),
        _cleanup_rate_limiter(),
    ]

    payload = {
        "event": "cleanup-complete",
        "phase": args.phase,
        "results": [result.to_dict() for result in results],
        "timestamp": int(time.time()),
    }
    _log(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
