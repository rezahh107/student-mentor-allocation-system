"""Deterministic debug helpers for hardened FastAPI applications."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from .state import InMemoryStore


def _extract_store_snapshot(store: InMemoryStore | None) -> dict[str, Any]:
    """Return a deterministic snapshot of an ``InMemoryStore``.

    Args:
        store: Optional store instance to serialise.

    Returns:
        Dictionary containing namespace and sorted keys for the store.
    """

    if store is None:
        return {"keys": [], "namespace": None}
    keys = sorted(store.keys())
    return {"keys": keys, "namespace": store.namespace}


def _middleware_chain(app: FastAPI) -> list[str]:
    """Return middleware class names in execution order.

    Args:
        app: FastAPI application exposing ``user_middleware``.

    Returns:
        Ordered list of middleware class names.
    """

    return [middleware.cls.__name__ for middleware in app.user_middleware]


def get_debug_context(app: FastAPI, *, correlation_id: str) -> dict[str, Any]:
    """Build a deterministic debug payload for assertions and logging.

    Args:
        app: FastAPI application exposing stateful testing attributes.
        correlation_id: Correlation identifier associated with the request.

    Returns:
        Dictionary containing Redis/idempotency snapshots and middleware metadata.
    """

    rate_store: InMemoryStore | None = getattr(app.state, "rate_store", None)
    idem_store: InMemoryStore | None = getattr(app.state, "idempotency_store", None)
    clock = getattr(app.state, "clock", None)
    timestamp = clock.now().isoformat() if clock is not None else None
    env = os.getenv("GITHUB_ACTIONS", "local")
    return {
        "redis_keys": _extract_store_snapshot(rate_store),
        "idempotency": _extract_store_snapshot(idem_store),
        "middleware_order": _middleware_chain(app),
        "env": env,
        "timestamp": timestamp,
        "correlation_id": correlation_id,
    }


__all__ = ["get_debug_context"]
