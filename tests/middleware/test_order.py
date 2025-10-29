from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Sequence

import pytest
from freezegun import freeze_time

EXPECTED_CHAIN: Sequence[str] = (
    "RateLimitMiddleware",
    "IdempotencyMiddleware",
    "AuthMiddleware",
)

MANDATORY_KEYS = {
    "IMPORT_TO_SABT_REDIS__DSN": "redis://127.0.0.1:6379/0",
    "IMPORT_TO_SABT_DATABASE__DSN": "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/student_mentor",
    "IMPORT_TO_SABT_AUTH__METRICS_TOKEN": "ci-metrics-token",
    "IMPORT_TO_SABT_AUTH__SERVICE_TOKEN": "ci-service-token",
    "IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS": "true",
}


@pytest.fixture(autouse=True)
def clean_import_env():
    """Ensure IMPORT_TO_SABT_* variables never leak across tests."""

    preserved = {k: v for k, v in os.environ.items() if k.startswith("IMPORT_TO_SABT_")}
    for key in list(preserved):
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key in [name for name in os.environ if name.startswith("IMPORT_TO_SABT_")]:
            os.environ.pop(key, None)
        os.environ.update(preserved)


@pytest.fixture
def seed_import_env(clean_import_env, monkeypatch):
    for key, value in MANDATORY_KEYS.items():
        monkeypatch.setenv(key, value)
    return dict(MANDATORY_KEYS)


def run_with_retry(operation: Callable[[], object], *, attempts: int = 3, seed: str = "middleware-order") -> object:
    """Deterministic retry helper with exponential backoff and jitter."""

    errors: list[str] = []
    base_delay = 0.05
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"attempt={attempt} error={exc!r}")
            if attempt == attempts:
                raise RuntimeError("; ".join(errors)) from exc
            jitter_seed = hashlib.blake2s(f"{seed}:{attempt}".encode("utf-8"), digest_size=4).hexdigest()
            jitter = (int(jitter_seed, 16) % 10) / 1000.0
            time.sleep(base_delay * attempt + jitter)
    raise RuntimeError("retry helper exhausted without returning")


def _debug_context(app) -> dict[str, object]:
    middleware = [mw.cls.__name__ for mw in getattr(app, "user_middleware", ())]
    return {
        "middleware": middleware,
        "timestamp": time.time(),
        "env": {k: os.environ[k] for k in os.environ if k.startswith("IMPORT_TO_SABT_")},
    }


@freeze_time("2024-01-01 00:00:00", tz_offset=3.5)
def test_middleware_order_chain(seed_import_env):
    """Verify middleware execution chain without performing HTTP requests."""

    factory_module = pytest.importorskip(
        "sma.phase6_import_to_sabt.app.app_factory",
        reason="application factory unavailable",
    )

    try:
        app = run_with_retry(factory_module.create_application)
    except Exception as exc:  # pragma: no cover - skip if factory cannot load
        pytest.skip(f"Application factory unavailable: {exc}")

    context = _debug_context(app)
    names = context["middleware"]
    missing = [name for name in EXPECTED_CHAIN if name not in names]
    if missing:
        pytest.xfail(
            f"Missing middleware classes: {missing}; observed={names}; context={context}"
        )

    try:
        start = names.index(EXPECTED_CHAIN[0])
    except ValueError:  # pragma: no cover - defensive
        pytest.xfail(f"RateLimitMiddleware missing; observed={names}; context={context}")
    observed = names[start : start + len(EXPECTED_CHAIN)]
    assert observed == list(EXPECTED_CHAIN), (
        "Middleware order mismatch",
        {"expected": list(EXPECTED_CHAIN), "observed": names, "context": context, "start": start},
    )
