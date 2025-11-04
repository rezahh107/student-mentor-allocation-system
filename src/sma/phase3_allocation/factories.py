"""Factory helpers wiring allocation components together."""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from .contracts import AllocationConfig
from .engine import AllocationEngine
from .policy import EligibilityPolicy
from .providers import SpecialSchoolsProvider
from .providers_db import DatabaseManagerCentersProvider


SessionFactory = Callable[[], Session]


def build_allocation_policy(
    session_factory: SessionFactory,
    *,
    special_schools_provider: SpecialSchoolsProvider,
    config: AllocationConfig | None = None,
    cache_ttl_seconds: int = 300,
    negative_cache_ttl_seconds: int = 60,
) -> EligibilityPolicy:
    """Create an ``EligibilityPolicy`` backed by the database providers."""

    manager_provider = DatabaseManagerCentersProvider(
        session_factory,
        cache_ttl_seconds=cache_ttl_seconds,
        negative_cache_ttl_seconds=negative_cache_ttl_seconds,
    )
    return EligibilityPolicy(special_schools_provider, manager_provider, config or AllocationConfig())


def build_allocation_engine(
    session_factory: SessionFactory,
    *,
    special_schools_provider: SpecialSchoolsProvider,
    config: AllocationConfig | None = None,
    cache_ttl_seconds: int = 300,
    negative_cache_ttl_seconds: int = 60,
) -> AllocationEngine:
    """Create an ``AllocationEngine`` pre-wired with DB-backed providers."""

    policy = build_allocation_policy(
        session_factory,
        special_schools_provider=special_schools_provider,
        config=config,
        cache_ttl_seconds=cache_ttl_seconds,
        negative_cache_ttl_seconds=negative_cache_ttl_seconds,
    )
    return AllocationEngine(policy=policy, config=config)
