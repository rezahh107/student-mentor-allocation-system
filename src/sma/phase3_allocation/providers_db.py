"""Database-backed providers for allocation dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Callable, FrozenSet

from sqlalchemy import select
from sqlalchemy.orm import Session

from sma.infrastructure.persistence.models import ManagerAllowedCenterModel, ManagerModel

from .providers import ManagerCentersProvider


SessionFactory = Callable[[], Session]


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    value: FrozenSet[int] | object


class DatabaseManagerCentersProvider(ManagerCentersProvider):
    """Load manager allowed centers from the database with lightweight caching."""

    _NOT_FOUND = object()

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        cache_ttl_seconds: int = 300,
        negative_cache_ttl_seconds: int = 60,
    ) -> None:
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        if negative_cache_ttl_seconds <= 0:
            raise ValueError("negative_cache_ttl_seconds must be positive")
        self._session_factory = session_factory
        self._cache_ttl = float(cache_ttl_seconds)
        self._negative_cache_ttl = float(negative_cache_ttl_seconds)
        self._cache: dict[int, _CacheEntry] = {}
        self._lock = RLock()

    def get_allowed_centers(self, manager_id: int) -> FrozenSet[int] | None:
        now = monotonic()
        with self._lock:
            cached = self._cache.get(manager_id)
            if cached and cached.expires_at > now:
                if cached.value is self._NOT_FOUND:
                    return None
                return cached.value  # type: ignore[return-value]

        centers = self._load_centers(manager_id)
        expires_at = now + (self._cache_ttl if centers is not None else self._negative_cache_ttl)
        cache_value: FrozenSet[int] | object = centers if centers is not None else self._NOT_FOUND
        with self._lock:
            self._cache[manager_id] = _CacheEntry(expires_at=expires_at, value=cache_value)
        return centers

    def clear(self) -> None:
        """Invalidate the in-memory cache."""

        with self._lock:
            self._cache.clear()

    def _load_centers(self, manager_id: int) -> FrozenSet[int] | None:
        with self._session_factory() as session:
            manager = session.get(ManagerModel, manager_id)
            if manager is None or not manager.is_active:
                return None
            stmt = (
                select(ManagerAllowedCenterModel.center_code)
                .where(ManagerAllowedCenterModel.manager_id == manager_id)
            )
            centers = session.execute(stmt).scalars().all()
        if not centers:
            return frozenset()
        return frozenset(int(code) for code in centers)
