from __future__ import annotations

"""Read-only adapter that queries the reporting replica with backoff."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2b
from typing import Any, Dict, Iterable, List, Protocol

from prometheus_client import Counter, Histogram

from .metrics import OPS_READ_RETRIES

logger = logging.getLogger(__name__)


class AsyncConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> Iterable[Dict[str, Any]]:  # pragma: no cover - protocol
        ...


class AsyncConnectionFactory(Protocol):
    async def __call__(self) -> AsyncConnection:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class ReplicaResult:
    """Container for replica query results."""

    rows: List[Dict[str, Any]]
    generated_at: datetime


class ReplicaTimeoutError(RuntimeError):
    """Raised when the replica cannot be reached within the configured budget."""


READ_LATENCY = Histogram(
    "ops_replica_read_latency_seconds",
    "Latency for replica reads",
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5),
)
READ_FAILURES = Counter(
    "ops_replica_read_failures_total",
    "Number of replica read failures",
    ["reason"],
)
READ_ATTEMPTS = Counter(
    "ops_replica_read_attempts_total",
    "Number of replica read attempts",
    ["phase"],
)


class DeterministicClock(Protocol):
    def now(self) -> datetime:  # pragma: no cover - protocol
        ...


class ReplicaAdapter:
    """Async adapter executing read-only queries against the replica."""

    def __init__(
        self,
        connection_factory: AsyncConnectionFactory,
        clock: DeterministicClock,
        *,
        timeout_seconds: float = 0.4,
        attempts: int = 3,
    ) -> None:
        self._connection_factory = connection_factory
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._attempts = attempts

    async def _run_with_retry(self, query_name: str, query: str, *args: Any) -> ReplicaResult:
        READ_ATTEMPTS.labels(phase=query_name).inc()

        async def _execute() -> ReplicaResult:
            started = self._clock.now()
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    connection = await self._connection_factory()
                    rows = [dict(row) for row in await connection.fetch(query, *args)]
                    READ_LATENCY.observe((self._clock.now() - started).total_seconds())
                    return ReplicaResult(rows=rows, generated_at=self._clock.now())
            except Exception as exc:  # pragma: no cover - instrumentation path
                raise ReplicaTimeoutError("خطای اتصال به مخزن گزارش‌گیری") from exc

        last_exc: ReplicaTimeoutError | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                return await _execute()
            except ReplicaTimeoutError as exc:
                READ_FAILURES.labels(reason="timeout").inc()
                OPS_READ_RETRIES.inc()
                logger.warning(
                    "replica-read-timeout",
                    extra={
                        "rid": "ops-replica",
                        "op": query_name,
                        "namespace": "ops",
                        "actor_role": "system",
                        "center_scope": "*",
                        "last_error": str(exc),
                        "retry": attempt,
                    },
                )
                last_exc = exc
                if attempt == self._attempts:
                    break
                base_delay = min(0.05 * (2 ** (attempt - 1)), self._timeout_seconds)
                digest = blake2b(f"{query_name}:{attempt}".encode("utf-8"), digest_size=2).digest()
                jitter = int.from_bytes(digest, "big") / 65535 * 0.01
                await asyncio.sleep(base_delay + jitter)
        if last_exc is not None:
            raise last_exc
        raise ReplicaTimeoutError("خطای اتصال به مخزن گزارش‌گیری")

    async def fetch_exports(self, center: str | None = None) -> ReplicaResult:
        query = "SELECT * FROM exports_summary"
        params: List[Any] = []
        if center:
            query += " WHERE center_id = $1"
            params.append(center)
        return await self._run_with_retry("exports", query, *params)

    async def fetch_uploads(self, center: str | None = None) -> ReplicaResult:
        query = "SELECT * FROM uploads_summary"
        params: List[Any] = []
        if center:
            query += " WHERE center_id = $1"
            params.append(center)
        return await self._run_with_retry("uploads", query, *params)


def serialize_rows(rows: Iterable[Dict[str, Any]]) -> str:
    """Serialize rows for deterministic HTML rendering and testing."""

    return json.dumps(list(rows), ensure_ascii=False, sort_keys=True)


__all__ = ["ReplicaAdapter", "ReplicaResult", "ReplicaTimeoutError", "serialize_rows"]
