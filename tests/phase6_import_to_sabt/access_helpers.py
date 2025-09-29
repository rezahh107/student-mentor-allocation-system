from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Sequence

import httpx
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.phase6_import_to_sabt.app.app_factory import create_application
from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RedisConfig,
)
from src.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from src.phase6_import_to_sabt.app.timing import DeterministicTimer
from src.phase6_import_to_sabt.obs.metrics import ServiceMetrics, build_metrics


class SyncASGIClient:
    def __init__(self, app) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return asyncio.run(self._client.get(*args, **kwargs))

    def post(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return asyncio.run(self._client.post(*args, **kwargs))

    def close(self) -> None:
        asyncio.run(self._client.aclose())

    def __enter__(self) -> "SyncASGIClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


@dataclass(slots=True)
class AccessTestContext:
    client: SyncASGIClient
    metrics: ServiceMetrics
    registry: CollectorRegistry
    clock: FixedClock
    namespace: str


@contextmanager
def access_test_app(
    monkeypatch,
    *,
    tokens: Sequence[dict[str, object]],
    signing_keys: Sequence[dict[str, object]],
    download_ttl: int = 900,
    timer_durations: Sequence[float] | None = None,
    metrics_namespace: str | None = None,
    registry: CollectorRegistry | None = None,
) -> Iterator[AccessTestContext]:
    base_namespace = metrics_namespace or "import-to-sabt-test"
    namespace = f"{base_namespace}-{uuid.uuid4().hex}"
    tokens_env = f"TOKENS_{uuid.uuid4().hex}"
    signing_env = f"DOWNLOAD_KEYS_{uuid.uuid4().hex}"
    monkeypatch.setenv(tokens_env, json.dumps(list(tokens), ensure_ascii=False))
    monkeypatch.setenv(signing_env, json.dumps(list(signing_keys), ensure_ascii=False))

    registry = registry or CollectorRegistry()
    metrics = build_metrics(namespace, registry=registry)
    clock = FixedClock(datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Baku")))
    scripted_durations = list(timer_durations) if timer_durations is not None else [0.001, 0.001, 0.001]
    timer = DeterministicTimer(scripted_durations)
    rate_limit_store = InMemoryKeyValueStore(namespace=f"{namespace}:rate", clock=clock)
    idempotency_store = InMemoryKeyValueStore(namespace=f"{namespace}:idem", clock=clock)

    config = AppConfig(
        redis=RedisConfig(dsn="redis://localhost:6379/0", namespace=namespace, operation_timeout=0.2),
        database=DatabaseConfig(dsn="postgresql://localhost/test", statement_timeout_ms=500),
        auth=AuthConfig(
            metrics_token="",
            service_token="",
            tokens_env_var=tokens_env,
            download_signing_keys_env_var=signing_env,
            download_url_ttl_seconds=download_ttl,
        ),
        ratelimit=RateLimitConfig(namespace=namespace, requests=100, window_seconds=60, penalty_seconds=60),
        observability=ObservabilityConfig(service_name="import-to-sabt-test", metrics_namespace=namespace),
        timezone="Asia/Baku",
        readiness_timeout_seconds=0.1,
        health_timeout_seconds=0.1,
        enable_debug_logs=True,
        enable_diagnostics=True,
    )

    app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_limit_store,
        idempotency_store=idempotency_store,
        readiness_probes={},
        workflow=None,
    )

    with SyncASGIClient(app) as client:
        yield AccessTestContext(
            client=client,
            metrics=metrics,
            registry=registry,
            clock=clock,
            namespace=namespace,
        )

    metrics.reset()


__all__ = ["AccessTestContext", "access_test_app"]
