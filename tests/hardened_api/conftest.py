import asyncio
import json
import time
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sma.hardened_api.api import APISettings, create_app
from sma.hardened_api.auth_repository import APIKeyRecord, InMemoryAPIKeyRepository
from sma.hardened_api.middleware import (
    AuthConfig,
    RateLimitConfig,
    ensure_rate_limit_config_restored,
    rate_limit_config_guard,
    restore_rate_limit_config,
    snapshot_rate_limit_config,
)
from sma.hardened_api.observability import hash_national_id, metrics_registry_guard


class FrozenClock:
    def __init__(self, *, start: float | None = None) -> None:
        self._initial = start or 1_000_000.0
        self._time = self._initial
        self._lock = asyncio.Lock()

    async def advance(self, seconds: float) -> None:
        async with self._lock:
            self._time += seconds

    async def time(self) -> float:
        async with self._lock:
            return self._time

    async def monotonic(self) -> float:
        return await self.time()

    async def reset(self) -> None:
        async with self._lock:
            self._time = self._initial


class FakeRedis:
    def __init__(self, *, clock: FrozenClock | None = None) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._zsets: dict[str, dict[str, float]] = {}
        self._lock = asyncio.Lock()
        self._clock = clock or FrozenClock()

    async def _now(self) -> float:
        return await self._clock.time()

    async def _cleanup(self, key: str) -> None:
        expires = self._expiry.get(key)
        if expires and expires <= await self._now():
            self._data.pop(key, None)
            self._zsets.pop(key, None)
            self._expiry.pop(key, None)

    async def set(self, name: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        async with self._lock:
            await self._cleanup(name)
            if nx and name in self._data:
                return False
            self._data[name] = value
            if ex:
                self._expiry[name] = await self._now() + ex
            return True

    async def get(self, name: str) -> bytes | None:
        async with self._lock:
            await self._cleanup(name)
            value = self._data.get(name)
            if value is None:
                return None
            return value.encode("utf-8")

    async def delete(self, name: str) -> int:
        async with self._lock:
            existed = name in self._data or name in self._zsets
            self._data.pop(name, None)
            self._zsets.pop(name, None)
            self._expiry.pop(name, None)
            return 1 if existed else 0

    async def expire(self, name: str, time_seconds: int) -> bool:
        async with self._lock:
            if name not in self._data and name not in self._zsets:
                return False
            self._expiry[name] = await self._now() + time_seconds
            return True

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        async with self._lock:
            zset = self._zsets.setdefault(name, {})
            zset.update(mapping)
            return len(mapping)

    async def zremrangebyscore(self, name: str, min: float, max: float) -> int:
        async with self._lock:
            zset = self._zsets.setdefault(name, {})
            removed = [member for member, score in zset.items() if min <= score <= max]
            for member in removed:
                zset.pop(member, None)
            return len(removed)

    async def zcard(self, name: str) -> int:
        async with self._lock:
            zset = self._zsets.setdefault(name, {})
            return len(zset)

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        keys = keys_and_args[:numkeys]
        args = keys_and_args[numkeys:]
        if script.startswith("local lock"):
            lock, redis_key = keys
            body_hash, ttl, now = args
            ttl = int(ttl)
            now = int(now)
            async with self._lock:
                await self._cleanup(redis_key)
                if lock not in self._data:
                    self._data[lock] = str(now)
                    self._expiry[lock] = await self._now() + ttl
                    payload = json.dumps({"status": "pending", "body_hash": body_hash, "created_at": now})
                    self._data[redis_key] = payload
                    self._expiry[redis_key] = await self._now() + ttl
                    return "reserved"
                cached = self._data.get(redis_key)
                if cached is None:
                    return "retry"
                decoded = json.loads(cached)
                if decoded.get("body_hash") != body_hash:
                    return "conflict"
                if decoded.get("status") == "completed":
                    return cached
                return "wait"
        stripped = script.lstrip()
        if stripped.startswith("-- counter_allocate"):
            student_key, sequence_key = keys
            placeholder, year_code, prefix, center, gender, seq_max, ttl_ms = args
            seq_max = int(seq_max)
            ttl = int(ttl_ms) / 1000.0
            async with self._lock:
                await self._cleanup(student_key)
                await self._cleanup(sequence_key)
                existing = self._data.get(student_key)
                if existing:
                    try:
                        decoded = json.loads(existing)
                    except json.JSONDecodeError:
                        decoded = {"status": "PENDING"}
                    status = decoded.get("status")
                    if status == "PENDING":
                        return json.dumps({"status": "PENDING"})
                    if status == "ASSIGNED":
                        return json.dumps(
                            {
                                "status": "REUSED",
                                "counter": decoded.get("counter"),
                                "serial": decoded.get("serial"),
                            }
                        )
                self._data[student_key] = placeholder
                self._expiry[student_key] = await self._now() + ttl
                current_raw = self._data.get(sequence_key)
                current = int(current_raw) if current_raw else 0
                current += 1
                self._data[sequence_key] = str(current)
                if current > seq_max:
                    self._data.pop(student_key, None)
                    self._expiry.pop(student_key, None)
                    return json.dumps({"status": "EXHAUSTED"})
                serial = f"{current:04d}"
                counter = f"{year_code}{prefix}{serial}"
                payload = json.dumps(
                    {
                        "status": "ASSIGNED",
                        "counter": counter,
                        "center": center,
                        "gender": gender,
                        "serial": serial,
                        "year_code": year_code,
                    }
                )
                self._data[student_key] = payload
                self._expiry.pop(student_key, None)
                return json.dumps({"status": "NEW", "counter": counter, "serial": serial})
        if "ZRANGE" in script:
            key = keys[0]
            async with self._lock:
                zset = self._zsets.setdefault(key, {})
                if not zset:
                    return 0
                member, score = sorted(zset.items(), key=lambda item: item[1])[0]
                return float(score)
        raise RuntimeError(f"Unsupported script: {script[:40]}")

    async def exists(self, name: str) -> bool:
        async with self._lock:
            await self._cleanup(name)
            return name in self._data

    async def flushdb(self) -> None:
        async with self._lock:
            self._data.clear()
            self._zsets.clear()
            self._expiry.clear()


@dataclass(slots=True)
class FakeAllocator:
    calls: list[Any]

    def __init__(self) -> None:
        self.calls = []

    def allocate(self, request):
        self.calls.append(request)
        return type(
            "Result",
            (),
            {
                "allocation_id": len(self.calls),
                "allocation_code": f"AC{len(self.calls):04d}",
                "year_code": "04",
                "mentor_id": request.mentor_id,
                "status": "accepted",
                "message": "ثبت شد",
                "error_code": None,
            },
        )()


def build_counter_app(
    namespace: str | None = None,
    *,
    metrics_token: str | None = None,
    metrics_ip_allowlist: list[str] | None = None,
    redis_client: Any | None = None,
    allocator: FakeAllocator | None = None,
    auth_config: AuthConfig | None = None,
    settings_overrides: dict[str, Any] | None = None,
) -> tuple[Any, Any]:
    redis_backend = redis_client or FakeRedis()
    allocator_impl = allocator or FakeAllocator()
    salt = "testsalt"
    raw_key = "STATICKEY1234567890"
    repository = InMemoryAPIKeyRepository(
        [APIKeyRecord(name="fixture", key_hash=hash_national_id(raw_key, salt=salt))]
    )
    auth = auth_config or AuthConfig(
        bearer_secret="secret-key",
        api_key_salt=salt,
        accepted_audience={"alloc"},
        accepted_issuers={"issuer"},
        allow_plain_tokens={"TESTTOKEN1234567890"},
        api_key_repository=repository,
    )
    settings_kwargs: dict[str, Any] = {
        "redis_namespace": namespace or f"test-{uuid.uuid4()}",
        "metrics_token": metrics_token,
        "metrics_ip_allowlist": metrics_ip_allowlist or ["127.0.0.1"],
    }
    if settings_overrides:
        settings_kwargs.update(settings_overrides)
    settings = APISettings(**settings_kwargs)
    app = create_app(
        allocator=allocator_impl,
        settings=settings,
        auth_config=auth,
        redis_client=redis_backend,
    )
    return app, redis_backend


def _extract_rate_limit_config(app: Any) -> RateLimitConfig:
    application = getattr(app, "app", app)
    return application.state.middleware_state.rate_limit_config  # type: ignore[attr-defined]


@contextmanager
def temporary_rate_limit_config(app: Any) -> Iterator[RateLimitConfig]:
    config = _extract_rate_limit_config(app)
    with rate_limit_config_guard(config) as guarded_config:
        yield guarded_config


@pytest.fixture(scope="function")
def frozen_clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture(scope="function")
def redis_client(frozen_clock: FrozenClock) -> FakeRedis:
    return FakeRedis(clock=frozen_clock)


@pytest.fixture(scope="function")
def auth_config(redis_client: FakeRedis) -> AuthConfig:
    salt = "testsalt"
    raw = "STATICKEY1234567890"
    hashed = hash_national_id(raw, salt=salt)
    repository = InMemoryAPIKeyRepository([APIKeyRecord(name="fixture", key_hash=hashed)])
    return AuthConfig(
        bearer_secret="secret-key",
        api_key_salt=salt,
        accepted_audience={"alloc"},
        accepted_issuers={"issuer"},
        allow_plain_tokens={"TESTTOKEN1234567890"},
        api_key_repository=repository,
    )


@pytest.fixture(scope="function")
def allocator() -> FakeAllocator:
    return FakeAllocator()


@pytest.fixture(scope="function")
def app(allocator: FakeAllocator, auth_config: AuthConfig, redis_client: FakeRedis):
    settings = APISettings(redis_namespace=f"test-{uuid.uuid4()}")
    application = create_app(
        allocator=allocator,
        settings=settings,
        auth_config=auth_config,
        redis_client=redis_client,
    )
    config = _extract_rate_limit_config(application)
    snapshot = snapshot_rate_limit_config(config)
    try:
        yield application
        ensure_rate_limit_config_restored(
            config,
            snapshot,
            context="app fixture",
        )
    finally:
        restore_rate_limit_config(config, snapshot)


@pytest_asyncio.fixture(scope="function")
async def client(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        setattr(async_client, "app", app)
        yield async_client


@pytest.fixture(scope="function", autouse=True)
def clean_metrics_registry() -> Iterator[None]:
    with metrics_registry_guard():
        yield


@pytest_asyncio.fixture(scope="function")
async def clean_state(app, redis_client: FakeRedis, frozen_clock: FrozenClock):
    await redis_client.flushdb()
    if hasattr(redis_client, "_data"):
        assert getattr(redis_client, "_data") == {}
        assert getattr(redis_client, "_zsets") == {}
        assert getattr(redis_client, "_expiry") == {}
    await app.state.api_state.reset()
    await frozen_clock.reset()
    yield
    await redis_client.flushdb()
    if hasattr(redis_client, "_data"):
        assert getattr(redis_client, "_data") == {}
        assert getattr(redis_client, "_zsets") == {}
        assert getattr(redis_client, "_expiry") == {}
    await app.state.api_state.reset()
    await frozen_clock.reset()


async def make_request_with_retry(
    client: AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    backoff: float = 0.1,
    **kwargs,
):
    last_response = None
    for attempt in range(1, max_attempts + 1):
        response = await client.request(method, url, **kwargs)
        if response.status_code < 500:
            return response
        last_response = response
        if attempt < max_attempts:
            await asyncio.sleep(backoff * attempt)
    return last_response


def verify_middleware_order(app: Any) -> None:
    application = getattr(app, "app", app)
    names = [mw.cls.__name__ for mw in application.user_middleware]
    assert "RateLimitMiddleware" in names, names
    execution = list(reversed(names))
    assert execution.index("RateLimitMiddleware") < execution.index("IdempotencyMiddleware") < execution.index(
        "AuthenticationMiddleware"
    ), execution


def setup_test_data(unique_suffix: str) -> dict[str, Any]:
    return {
        "student_id": f"12345{unique_suffix}",
        "mentor_id": 100 + int(unique_suffix[-1]),
        "reg_center": 1,
        "reg_status": 1,
        "gender": 1,
        "phone": "09121234567",
        "national_id": "1234567890",
    }


async def assert_clean_final_state(app_or_client: Any) -> None:
    application = getattr(app_or_client, "app", app_or_client)
    await application.state.api_state.reset()  # type: ignore[attr-defined]


def get_debug_context(
    app: Any | None = None,
    *,
    redis_client: FakeRedis | None = None,
    rate_limit_state: RateLimitConfig | None = None,
) -> dict[str, Any]:
    ctx = {"timestamp": time.time()}
    if app is not None:
        application = getattr(app, "app", app)
        ctx["middleware"] = [mw.cls.__name__ for mw in application.user_middleware]
    if redis_client is not None:
        ctx["redis_keys"] = list(redis_client._data.keys())  # noqa: SLF001 - debug helper
    if rate_limit_state is not None:
        ctx["rate_limit_default"] = {
            "requests": rate_limit_state.default_rule.requests,
            "window": rate_limit_state.default_rule.window_seconds,
        }
    return ctx
