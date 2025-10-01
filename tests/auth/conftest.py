from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from auth.metrics import AuthMetrics
from auth.session_store import SessionStore
from src.reliability.clock import Clock
from tests.mock.oidc import MockOIDCProvider
from tests.mock.saml import MockSAMLProvider


def _extract_clock(source: Any) -> Any:
    return getattr(source, "clock", source)


@pytest.fixture(name="sso_clock")
def sso_clock_fixture() -> SimpleNamespace:
    holder = [datetime(2024, 3, 21, 9, 0, tzinfo=timezone.utc)]
    tz = ZoneInfo("Asia/Tehran")

    def now() -> datetime:
        return holder[0]

    clock = Clock(timezone=tz, _now_factory=now)

    def advance(seconds: int) -> None:
        holder[0] = holder[0] + timedelta(seconds=seconds)

    def set_time(value: datetime) -> None:
        holder[0] = value

    return SimpleNamespace(clock=clock, advance=advance, set=set_time)


@pytest.fixture
def session_store(sso_clock: SimpleNamespace):
    from src.fakeredis import FakeStrictRedis

    redis = FakeStrictRedis()
    store = SessionStore(redis, ttl_seconds=900, clock=_extract_clock(sso_clock), namespace=f"sso:{id(redis)}")
    try:
        yield store
    finally:
        redis.flushdb()


@pytest.fixture
def auth_metrics():
    metrics = AuthMetrics.build()
    yield metrics


@pytest.fixture
def audit_log():
    events: list[dict[str, Any]] = []

    async def sink(action: str, correlation_id: str, payload: dict[str, Any]) -> None:
        events.append({"action": action, "correlation_id": correlation_id, **payload})

    yield SimpleNamespace(events=events, sink=sink)


@pytest.fixture
def oidc_provider(sso_clock: SimpleNamespace):
    provider = MockOIDCProvider(clock=_extract_clock(sso_clock))
    yield provider


@pytest.fixture
def oidc_http_client(oidc_provider: MockOIDCProvider):
    client = httpx.AsyncClient(transport=oidc_provider.transport, base_url=oidc_provider.issuer)
    try:
        yield client
    finally:
        asyncio.run(client.aclose())


@pytest.fixture
def saml_provider(sso_clock: SimpleNamespace):
    provider = MockSAMLProvider(clock=_extract_clock(sso_clock))
    yield provider
