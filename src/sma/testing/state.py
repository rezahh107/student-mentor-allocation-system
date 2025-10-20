"""Deterministic helpers for state hygiene fixtures."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
from typing import Iterable

LOGGER = logging.getLogger("sma.testing.state")


def _emit(event: str, *, correlation_id: str | None = None, **extra: object) -> None:
    payload = {
        "event": event,
        "correlation_id": correlation_id,
        **extra,
    }
    LOGGER.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def get_test_namespace() -> str:
    """Return a deterministic namespace for Redis/DB keys during tests."""

    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    digest = hashlib.blake2s(str(repo_root).encode("utf-8"), digest_size=6).hexdigest()
    return f"sma:test:{worker}:{digest}"


def maybe_connect_redis(
    url_envs: Iterable[str] = ("REDIS_URL", "TEST_REDIS_URL"),
    *,
    correlation_id: str | None = None,
):
    """Attempt to connect to Redis; log and return ``None`` on failure."""

    for env_name in url_envs:
        url = os.environ.get(env_name)
        if not url:
            continue
        try:
            import redis  # type: ignore
        except ModuleNotFoundError:
            _emit(
                "redis-client-missing",
                correlation_id=correlation_id,
                env=env_name,
                message="پاک‌سازی فضای آزمون Redis انجام نشد؛ اتصال در دسترس نیست.",
            )
            return None
        try:
            client = redis.Redis.from_url(url, decode_responses=False)
            client.ping()
        except Exception:
            _emit(
                "redis-connection-failed",
                correlation_id=correlation_id,
                env=env_name,
                message="پاک‌سازی فضای آزمون Redis انجام نشد؛ اتصال در دسترس نیست.",
            )
            return None
        return client
    return None

