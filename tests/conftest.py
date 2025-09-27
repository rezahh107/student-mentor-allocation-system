from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import List

import pytest
from prometheus_client import CollectorRegistry
from starlette.testclient import TestClient
import pytest_asyncio

from phase6_import_to_sabt.app import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.observability import build_metrics
from phase6_import_to_sabt.app.probes import AsyncProbe, ProbeResult
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer


@pytest.fixture
def app_config() -> AppConfig:
    unique = uuid.uuid4().hex[:8]
    return AppConfig.model_validate(
        {
            "redis": {"dsn": "redis://localhost:6379/0", "namespace": f"test-{unique}", "operation_timeout": 0.2},
            "database": {"dsn": "postgresql://user:pass@localhost/db", "statement_timeout_ms": 500},
            "auth": {"metrics_token": "token۱۲۳", "service_token": "service-token"},
            "ratelimit": {"namespace": f"rl-{unique}", "requests": 2, "window_seconds": 60, "penalty_seconds": 120},
            "observability": {"service_name": "import-to-sabt", "metrics_namespace": f"import_to_sabt_{unique}"},
            "timezone": "Asia/Baku",
            "enable_diagnostics": True,
        }
    )


@pytest.fixture
def frozen_clock() -> FixedClock:
    moment = dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc)
    return FixedClock(moment)


@pytest.fixture
def deterministic_timer() -> DeterministicTimer:
    timer = DeterministicTimer([0.03, 0.04, 0.05, 0.02])
    yield timer
    timer.recorded.clear()


@pytest.fixture
def prom_registry_reset() -> List[CollectorRegistry]:
    registries: List[CollectorRegistry] = []
    yield registries
    for registry in registries:
        if hasattr(registry, "_names_to_collectors"):
            registry._names_to_collectors.clear()  # type: ignore[attr-defined]
        if hasattr(registry, "_collector_to_names"):
            registry._collector_to_names.clear()  # type: ignore[attr-defined]


@pytest.fixture
def service_metrics(app_config: AppConfig, prom_registry_reset: List[CollectorRegistry]):
    registry = CollectorRegistry()
    prom_registry_reset.append(registry)
    metrics = build_metrics(app_config.observability.metrics_namespace, registry)
    yield metrics
    metrics.reset()


@pytest.fixture(autouse=True)
def rate_limit_config_snapshot(app_config: AppConfig):
    snapshot = app_config.ratelimit.model_dump()
    yield
    assert app_config.ratelimit.model_dump() == snapshot


class StaticProbe:
    def __init__(self, component: str, healthy: bool, detail: str | None = None) -> None:
        self.component = component
        self.healthy = healthy
        self.detail = detail
        self.calls: list[float] = []

    async def __call__(self, timeout: float) -> ProbeResult:
        self.calls.append(timeout)
        return ProbeResult(component=self.component, healthy=self.healthy, detail=self.detail)


@pytest.fixture
def readiness_probes() -> dict[str, AsyncProbe]:
    return {
        "redis": StaticProbe("redis", True),
        "postgres": StaticProbe("postgres", True),
    }


@pytest.fixture
def async_app(
    app_config: AppConfig,
    frozen_clock: FixedClock,
    service_metrics,
    deterministic_timer: DeterministicTimer,
    readiness_probes: dict[str, AsyncProbe],
):
    namespace = f"test-{uuid.uuid4()}"
    rate_store = InMemoryKeyValueStore(namespace=f"{namespace}-rate", clock=frozen_clock)
    idem_store = InMemoryKeyValueStore(namespace=f"{namespace}-idem", clock=frozen_clock)
    app = create_application(
        app_config,
        clock=frozen_clock,
        metrics=service_metrics,
        timer=deterministic_timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes=readiness_probes,
    )
    yield app


class _ResponseWrapper:
    def __init__(self, response) -> None:
        self._response = response
        self.status_code = response.status_code
        self.headers = response.headers

    @property
    def text(self) -> str:
        return self._response.text

    def json(self):
        return self._response.json()


class AsyncTestClient:
    def __init__(self, app) -> None:
        self._client = TestClient(app)
        self._entered = False

    @property
    def app(self):
        return self._client.app

    async def __aenter__(self) -> "AsyncTestClient":
        if not self._entered:
            self._client.__enter__()
            self._entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._entered:
            self._client.__exit__(exc_type, exc, tb)
            self._entered = False

    async def request(self, method: str, url: str, *, headers=None, json=None):
        response = self._client.request(method, url, headers=headers, json=json)
        return _ResponseWrapper(response)

    async def get(self, url: str, *, headers=None):
        return await self.request("GET", url, headers=headers)

    async def post(self, url: str, *, headers=None, json=None):
        return await self.request("POST", url, headers=headers, json=json)


@pytest_asyncio.fixture
async def async_client(async_app) -> AsyncIterator[AsyncTestClient]:
    client = AsyncTestClient(async_app)
    try:
        await client.__aenter__()
        yield client
    finally:
        await client.__aexit__(None, None, None)
