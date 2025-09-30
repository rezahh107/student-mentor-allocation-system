"""Shared pytest fixtures respecting AGENTS determinism guidance."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest


os.environ.setdefault("RUN_PERFORMANCE_SUITE", "1")


pytest_plugins = (
    "pytest_asyncio",
    "tests.audit_retention.conftest",
    "tests.auth.conftest",
    "tests.fixtures.state",
    "tests.fixtures.debug_context",
    "tests.fixtures.factories",
    "tests.ops.conftest",
    "tests.plugins.pytest_asyncio_compat",
    "tests.plugins.session_stats",
    "tests.uploads.conftest",
    "pytester",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("env", "Environment variables for deterministic testing.", type="linelist", default=[])
    try:
        parser.addini(
            "asyncio_default_fixture_loop_scope",
            "Default asyncio fixture loop scope registered for pytest-asyncio.",
            default="function",
        )
    except ValueError:
        # Already registered by pytest-asyncio; ignore to keep determinism.
        pass


def pytest_configure(config: pytest.Config) -> None:
    for item in config.getini("env"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


if os.environ.get("TZ") != "Asia/Tehran":
    os.environ["TZ"] = "Asia/Tehran"
    if hasattr(time, "tzset"):
        time.tzset()


_TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


@dataclass
class DeterministicClock:
    """Deterministic clock aligned with AGENTS.md::Determinism."""

    _current: datetime

    def __call__(self) -> datetime:
        return self._current

    def now(self) -> datetime:
        return self._current

    def tick(self, *, seconds: float = 0.0) -> datetime:
        delta = timedelta(seconds=seconds)
        self._current = self._current + delta
        return self._current

    def freeze(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=_TEHRAN_TZ)
        self._current = value.astimezone(_TEHRAN_TZ)
        return self._current


@pytest.fixture()
def clock() -> Iterator[DeterministicClock]:
    """Provide deterministic time control per AGENTS.md::Testing & CI Gates."""

    timeline = DeterministicClock(
        _current=datetime(2024, 1, 1, 0, 0, tzinfo=_TEHRAN_TZ)
    )
    try:
        yield timeline
    finally:
        timeline.freeze(datetime(2024, 1, 1, 0, 0, tzinfo=_TEHRAN_TZ))
