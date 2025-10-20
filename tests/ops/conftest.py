from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from typing import Any, Dict, Iterable
from zoneinfo import ZoneInfo

import fakeredis
import pytest
import anyio
import httpx
from fastapi import FastAPI

from sma.ops.config import OpsSettings, SLOThresholds
from sma.ops.metrics import reset_metrics_registry
from sma.ops.replica_adapter import ReplicaAdapter
from sma.ops.router import build_ops_router
from sma.ops.service import OpsService


class StaticConnection:
    def __init__(self, exports: Iterable[Dict[str, Any]], uploads: Iterable[Dict[str, Any]]) -> None:
        self._exports = list(exports)
        self._uploads = list(uploads)

    async def fetch(self, query: str, *args: Any) -> list[Dict[str, Any]]:
        dataset = self._exports if "exports" in query else self._uploads
        if args:
            center = args[0]
            return [row for row in dataset if row.get("center_id") == center]
        return list(dataset)


class FrozenClock:
    def __init__(self) -> None:
        self._now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tehran"))

    def now(self) -> dt.datetime:
        return self._now


def get_debug_context(redis_client: fakeredis.FakeRedis) -> Dict[str, Any]:
    return {
        "redis_keys": sorted(k.decode() if isinstance(k, bytes) else k for k in redis_client.keys("*")),
        "env": "github-actions",
        "timestamp": 0,
    }


class SyncASGIClient:
    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self.state = SimpleNamespace()

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        async def _call() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path, **kwargs)

        return anyio.run(_call)

    def close(self) -> None:  # pragma: no cover - compatibility shim
        return None


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ops_settings() -> OpsSettings:
    return OpsSettings(
        reporting_replica_dsn="postgresql://user:pass@localhost:5432/replica",
        metrics_read_token="metrics-token-123456",
        slo_thresholds=SLOThresholds(
            healthz_p95_ms=120,
            readyz_p95_ms=150,
            export_p95_ms=800,
            export_error_budget=42,
        ),
    )


@pytest.fixture
def clean_state() -> fakeredis.FakeRedis:
    redis_client = fakeredis.FakeStrictRedis()
    redis_client.flushdb()
    reset_metrics_registry()
    yield redis_client
    redis_client.flushdb()
    reset_metrics_registry()


@pytest.fixture
def build_ops_client(
    request: pytest.FixtureRequest,
    frozen_clock: FrozenClock,
    ops_settings: OpsSettings,
    clean_state: fakeredis.FakeRedis,
):
    def _builder(
        *,
        exports: Iterable[Dict[str, Any]],
        uploads: Iterable[Dict[str, Any]],
        fail_exports: bool = False,
        fail_uploads: bool = False,
    ) -> SyncASGIClient:
        async def _connection_factory() -> StaticConnection:
            await asyncio.sleep(0)
            return StaticConnection(exports, uploads)

        adapter = ReplicaAdapter(_connection_factory, frozen_clock)

        class _Service(OpsService):
            async def load_exports(self, ctx):  # type: ignore[override]
                if fail_exports:
                    raise RuntimeError("exports-failure")
                return await super().load_exports(ctx)

            async def load_uploads(self, ctx):  # type: ignore[override]
                if fail_uploads:
                    raise RuntimeError("uploads-failure")
                return await super().load_uploads(ctx)

        service = _Service(adapter)

        def factory(_: OpsSettings) -> OpsService:
            return service

        app = FastAPI()
        app.include_router(build_ops_router(factory, settings=ops_settings))

        client = SyncASGIClient(app)
        client.state.redis = clean_state
        request.addfinalizer(client.close)
        return client

    return _builder
