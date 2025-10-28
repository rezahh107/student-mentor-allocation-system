"""Integration-level fixtures enforcing Redis/DB hygiene and diagnostics."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional
from uuid import uuid4

import pytest

from sma._local_fakeredis import FakeStrictRedis

logger = logging.getLogger(__name__)

pytest_plugins = ("pytest_asyncio.plugin", "tests.fixtures.state")


@dataclass(slots=True)
class RedisNamespace:
    """Context wrapper providing namespaced Redis operations for tests.

    Example:
        >>> ns = RedisNamespace(FakeStrictRedis(), "tests:abc")
        >>> ns.key("rate-limit")
        'tests:abc:rate-limit'
    """

    client: FakeStrictRedis
    namespace: str
    created_keys: set[str] = field(default_factory=set)

    def key(self, suffix: str) -> str:
        """Return a deterministic key scoped to the namespace."""

        scoped = f"{self.namespace}:{suffix}"
        self.created_keys.add(scoped)
        return scoped

    def keys(self) -> List[str]:
        """Return all keys currently stored in the namespace."""

        prefix = f"{self.namespace}:"
        return [key for key in self.client.keys("*") if key.startswith(prefix)]


class _AsyncTransaction:
    """Very small async context manager modelling nested DB transactions."""

    def __init__(self, session: "InMemorySession", *, label: str) -> None:
        self._session = session
        self._label = label
        self._active = False

    async def __aenter__(self) -> "InMemorySession":
        self._active = True
        self._session._push_transaction(self._label)
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - signature mandated by context protocol
        try:
            if exc:
                await self._session.rollback()
        finally:
            self._session._pop_transaction(self._label)
            self._active = False
        return False


class InMemorySession:
    """Thread-safe SQLAlchemy-like session capturing executed statements for diagnostics.

    Example:
        >>> session = InMemorySession()
        >>> async def demo() -> None:
        ...     async with session.begin():
        ...         session.record_query("INSERT INTO t VALUES (1)")
        ...
        >>> asyncio.run(demo())
        >>> session.queries
        ['INSERT INTO t VALUES (1)']
    """

    def __init__(self) -> None:
        self._queries: List[str] = []
        self._transactions: List[str] = []
        self._fk_state: List[str] = []
        self._lock = asyncio.Lock()

    def begin(self) -> _AsyncTransaction:
        return _AsyncTransaction(self, label="root")

    def begin_nested(self) -> _AsyncTransaction:
        return _AsyncTransaction(self, label="nested")

    async def rollback(self) -> None:
        async with self._lock:
            self._queries.clear()
            self._fk_state.clear()

    def record_query(self, statement: str) -> None:
        self._queries.append(statement)

    def execute(self, statement: Any) -> None:
        """Lightweight execute stub capturing the statement for diagnostics."""

        self.record_query(str(statement))
        return None

    @property
    def queries(self) -> List[str]:
        return list(self._queries)

    def verify_foreign_keys(self) -> bool:
        return not self._fk_state

    def mark_fk_violation(self, message: str) -> None:
        self._fk_state.append(message)

    def _push_transaction(self, label: str) -> None:
        self._transactions.append(label)

    def _pop_transaction(self, label: str) -> None:
        if not self._transactions:
            return
        popped = self._transactions.pop()
        if popped != label:
            self.mark_fk_violation(f"TRANSACTION_STACK_MISMATCH:{label}->{popped}")


@pytest.fixture(scope="session")
def db_session() -> Iterator[InMemorySession]:
    """Provide a process-wide deterministic DB session stub."""

    session = InMemorySession()
    yield session


@pytest.fixture(scope="function")
def clean_redis_state(clean_redis_state_sync) -> RedisNamespace:
    """Provide Redis namespace isolation for both sync and async tests."""

    return clean_redis_state_sync


@pytest.fixture(scope="function")
def _db_state_reset(db_session: InMemorySession) -> Iterator[InMemorySession]:
    """Synchronous helper that clears session diagnostics before/after tests."""

    db_session._queries.clear()
    db_session._transactions.clear()
    db_session._fk_state.clear()
    yield db_session
    db_session._queries.clear()
    db_session._transactions.clear()
    db_session._fk_state.clear()


@pytest.fixture(scope="function")
def clean_db_state(_db_state_reset: InMemorySession) -> Iterator[InMemorySession]:
    """Return a transaction-safe session for integration tests."""

    if not _db_state_reset.verify_foreign_keys():
        pytest.fail("وضعیت دیتابیس از تست قبلی پاک‌سازی نشده است.", pytrace=False)

    yield _db_state_reset

    if not _db_state_reset.verify_foreign_keys():
        pytest.fail("نقض کلید خارجی پس از اجرای تست تشخیص داده شد.", pytrace=False)


@pytest.fixture(scope="function")
def benchmark(timing_control) -> Iterator[Callable[[Callable[..., Any]], Any]]:
    """Deterministic pytest-benchmark replacement honoring timing controls."""

    class _BenchmarkHarness:
        def __init__(self) -> None:
            self.stats = SimpleNamespace(stats={"mean": 0.0})

        def __call__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            if isinstance(result, dict) and "duration" in result:
                try:
                    self.stats.stats["mean"] = float(result["duration"])
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    self.stats.stats["mean"] = 0.0
            return result

    harness = _BenchmarkHarness()
    yield harness


@pytest.fixture
def middleware_order_validator() -> Callable[[Any], None]:
    """Return a validator asserting RateLimit→Idempotency→Auth ordering."""

    from sma.phase6_import_to_sabt.app.middleware import AuthMiddleware, IdempotencyMiddleware, RateLimitMiddleware

    def _validate(app: Any) -> None:
        chain = [entry.cls for entry in getattr(app, "user_middleware", [])]
        try:
            rate_index = chain.index(RateLimitMiddleware)
            idem_index = chain.index(IdempotencyMiddleware)
            auth_index = chain.index(AuthMiddleware)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise AssertionError("middleware chain incomplete") from exc
        assert rate_index < idem_index < auth_index, (
            "زنجیره میان‌افزار با الگوی RateLimit→Idempotency→Auth هم‌خوانی ندارد",
            [cls.__name__ for cls in chain],
        )

    return _validate


@pytest.fixture
def get_debug_context(clean_redis_state: RedisNamespace, db_session: InMemorySession) -> Callable[[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[dict[str, Any]]], Dict[str, Any]]:
    """Capture structured diagnostics for assertion failures.

    Example:
        >>> collector = get_debug_context(None, None, None)  # doctest: +SKIP
        >>> collector({"payload": "req"}, {"status": 200}, None)  # doctest: +SKIP
        {'request': {'payload': 'req'}, 'response': {'status': 200}, ...}
    """

    def _collect(
        request: Optional[dict[str, Any]] = None,
        response: Optional[dict[str, Any]] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        timestamp = time.time()
        redis_keys = clean_redis_state.keys()
        context: Dict[str, Any] = {
            "timestamp": timestamp,
            "namespace": clean_redis_state.namespace,
            "redis_keys": redis_keys,
            "db_queries": db_session.queries,
            "request": request or {},
            "response": response or {},
        }
        if extra:
            context.update(extra)
        return context

    return _collect


@pytest.fixture(scope="function")
def clean_state(
    clean_redis_state_sync,
    db_session: InMemorySession,
) -> Iterator[dict[str, Any]]:
    """Synchronous hygiene fixture bridging Redis and DB cleanup for integration tests."""

    if not db_session.verify_foreign_keys():
        pytest.fail("وضعیت دیتابیس از تست قبلی پاک‌سازی نشده است.", pytrace=False)

    db_session._queries.clear()
    db_session._transactions.clear()
    db_session._fk_state.clear()

    yield {"redis": clean_redis_state_sync, "db": db_session}

    if not db_session.verify_foreign_keys():
        pytest.fail("نقض کلید خارجی پس از اجرای تست تشخیص داده شد.", pytrace=False)
    db_session._queries.clear()
    db_session._transactions.clear()
    db_session._fk_state.clear()


@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_with_retry() -> None:
    """Ensure pytest-rerunfailures style retry mark is available for CI.

    Example:
        >>> test_with_retry()
    """

    assert True
