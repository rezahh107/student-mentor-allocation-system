"""Validate deterministic loading of ImportToSabt environment variables."""

from __future__ import annotations

import os
from typing import Dict
from uuid import uuid4

import pytest
from freezegun import freeze_time
from pydantic import ValidationError

from sma.phase6_import_to_sabt.app.config import AppConfig


def _debug_env_snapshot(env_values: Dict[str, str]) -> Dict[str, str | None]:
    """Return a safe snapshot of ImportToSabt-prefixed environment variables."""

    return {key: os.environ.get(key) for key in env_values}


def _build_env(namespace: str) -> Dict[str, str]:
    """Generate a deterministic set of nested env variables for tests."""

    return {
        "IMPORT_TO_SABT_DATABASE__DSN": "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/student_mentor",
        "IMPORT_TO_SABT_DATABASE__STATEMENT_TIMEOUT_MS": "500",
        "IMPORT_TO_SABT_REDIS__DSN": "redis://127.0.0.1:6379/0",
        "IMPORT_TO_SABT_REDIS__NAMESPACE": namespace,
        "IMPORT_TO_SABT_AUTH__SERVICE_TOKEN": "dev-service-token",
        "IMPORT_TO_SABT_AUTH__METRICS_TOKEN": "x",
        "IMPORT_TO_SABT_TIMEZONE": "Asia/Tehran",
    }


def _load_with_retry(max_attempts: int = 3) -> AppConfig:
    """Load config with deterministic exponential backoff semantics."""

    delay = 0.05
    schedule: list[float] = []
    for attempt in range(1, max_attempts + 1):
        try:
            return AppConfig.from_env()
        except ValidationError:
            schedule.append(delay)
            if attempt == max_attempts:
                raise
            delay = round(delay * 2, 3)
    raise AssertionError(f"unreachable retry exhaustion; schedule={schedule}")


@pytest.fixture(autouse=True)
def scrub_import_to_sabt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ImportToSabt env state is clean before and after each test."""

    preserved = {k: v for k, v in os.environ.items() if k.startswith("IMPORT_TO_SABT_")}
    for key in list(preserved):
        monkeypatch.delenv(key, raising=False)
    yield
    for key in list(os.environ.keys()):
        if key.startswith("IMPORT_TO_SABT_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in preserved.items():
        monkeypatch.setenv(key, value)


def test_app_config_from_nested_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loading nested env variables should populate config models correctly."""

    namespace = f"import_to_sabt_ci_{uuid4().hex}"
    env_map = _build_env(namespace)
    for key, value in env_map.items():
        monkeypatch.setenv(key, value)

    with freeze_time("2024-01-01T00:00:00Z"):
        cfg = _load_with_retry()

    assert cfg.database.dsn.startswith("postgresql+psycopg://"), (
        f"Database DSN mismatch. Snapshot: {_debug_env_snapshot(env_map)}"
    )
    assert cfg.redis.dsn.startswith("redis://"), (
        f"Redis DSN mismatch. Snapshot: {_debug_env_snapshot(env_map)}"
    )
    assert cfg.redis.namespace == namespace
    assert cfg.auth.metrics_token == "x"
    assert cfg.timezone == "Asia/Tehran"


def test_app_config_requires_database_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing required database block should raise a ValidationError without leaking secrets."""

    namespace = f"import_to_sabt_ci_{uuid4().hex}"
    env_map = _build_env(namespace)
    for key, value in env_map.items():
        monkeypatch.setenv(key, value)

    monkeypatch.delenv("IMPORT_TO_SABT_DATABASE__DSN", raising=False)

    with freeze_time("2024-01-01T00:00:00Z"):
        with pytest.raises(ValidationError) as exc_info:
            _load_with_retry()

    message = str(exc_info.value)
    assert "database" in message.lower(), f"Validation error missing database context: {message}"
    assert "postgresql+psycopg" not in message.lower()
    assert _debug_env_snapshot(env_map)  # force snapshot evaluation for debugging if failure occurs
