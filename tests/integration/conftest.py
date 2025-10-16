"""Integration-level fixtures enforcing Redis/DB hygiene and diagnostics."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional
from uuid import uuid4

import pytest

from src.fakeredis import FakeStrictRedis

logger = logging.getLogger(__name__)


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

    async def begin(self) -> _AsyncTransaction:
        return _AsyncTransaction(self, label="root")

    def begin_nested(self) -> _AsyncTransaction:
        return _AsyncTransaction(self, label="nested")

    async def rollback(self) -> None:
        async with self._lock:
            self._queries.clear()
            self._fk_state.clear()

    def record_query(self, statement: str) -> None:
        self._queries.append(statement)

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
async def clean_redis_state() -> AsyncIterator[RedisNamespace]:
    """Flush Redis before/after each test and log leaked keys."""

    client = FakeStrictRedis()
    namespace = f"tests:{uuid4().hex}"
    await asyncio.to_thread(client.flushdb)
    context = RedisNamespace(client=client, namespace=namespace)
    yield context
    leaked_keys = context.keys()
    await asyncio.to_thread(client.flushdb)
    if leaked_keys:
        logger.error("redis.leak.detected", extra={"namespace": namespace, "keys": leaked_keys})
        pytest.fail(f"کلیدهای ردیس پاک‌سازی نشدند: {leaked_keys}")


@pytest.fixture(scope="function")
async def clean_db_state(db_session: InMemorySession) -> AsyncIterator[InMemorySession]:
    """Wrap each test in a rollback-only transaction with FK verification."""

    async with db_session.begin():
        async with db_session.begin_nested():
            yield db_session
    await db_session.rollback()
    if not db_session.verify_foreign_keys():
        pytest.fail("نقض کلید خارجی پس از تست مشاهده شد.")


@pytest.fixture
def middleware_order_validator() -> Callable[[Any], None]:
    """Return a validator asserting RateLimit→Idempotency→Auth ordering."""

    from phase6_import_to_sabt.app.middleware import AuthMiddleware, IdempotencyMiddleware, RateLimitMiddleware

    def _validate(app: Any) -> None:
        chain = [entry.cls for entry in getattr(app, "user_middleware", [])]
        try:
            rate_index = chain.index(RateLimitMiddleware)
            idem_index = chain.index(IdempotencyMiddleware)
            auth_index = chain.index(AuthMiddleware)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise AssertionError("middleware chain incomplete") from exc
        assert rate_index > idem_index > auth_index, (
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


@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_with_retry() -> None:
    """Ensure pytest-rerunfailures style retry mark is available for CI.

    Example:
        >>> test_with_retry()
    """

    assert True
