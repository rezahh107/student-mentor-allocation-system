"""Root-level pytest configuration for shared CI expectations."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest

LEGACY_MARKERS: tuple[str, ...] = (
    "slow",
    "integration",
    "e2e",
    "qt",
    "db",
    "redis",
    "network",
    "perf",
    "flaky",
    "smoke",
)

_IGNORED_SEGMENTS: tuple[str, ...] = (
    "/legacy/",
    "/old_tests/",
    "/examples/",
    "/docs/",
    "/benchmarks/",
    "/tests/ci/",
    "/e2e/",
)

_ALLOWED_RELATIVE_TESTS: tuple[str, ...] = (
    "tests/test_phase6_middleware_order.py",
    "tests/test_phase6_metrics_guard.py",
    "tests/test_phase6_no_relative_imports.py",
    "tests/test_imports.py",
    "tests/validate_structure.py",
    "tests/excel/test_phase6_excel_safety.py",
    "tests/excel/test_phase6_atomic_writes.py",
    "tests/domain/test_phase6_counters_rules.py",
    "tests/api/test_phase6_persian_errors.py",
)

_ALLOWED_DIRECTORIES = {
    "tests",
    "tests/excel",
    "tests/domain",
    "tests/api",
}

_DEFAULT_TZ = ZoneInfo("Asia/Tehran")
_DEFAULT_START = datetime(2024, 1, 1, 0, 0, tzinfo=_DEFAULT_TZ)
_ROOT = Path(__file__).resolve().parents[1]


class DeterministicClock:
    """Deterministic clock with explicit tick control for tests."""

    def __init__(self, *, start: datetime | None = None) -> None:
        base = (start or _DEFAULT_START).astimezone(_DEFAULT_TZ)
        self._instant = base
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._instant

    def tick(self, *, seconds: float = 0.0) -> datetime:
        delta = timedelta(seconds=seconds)
        self._instant += delta
        self._monotonic += seconds
        return self._instant

    def monotonic(self) -> float:
        return self._monotonic

    def reset(self, *, start: datetime | None = None) -> None:
        base = (start or _DEFAULT_START).astimezone(_DEFAULT_TZ)
        self._instant = base
        self._monotonic = 0.0

    def __call__(self) -> datetime:  # pragma: no cover - convenience hook
        return self.now()


@pytest.fixture()
def clock() -> Iterator[DeterministicClock]:
    instance = DeterministicClock()
    yield instance
    instance.reset()


def _register_markers(config) -> None:  # type: ignore[no-untyped-def]
    config.addinivalue_line("markers", "asyncio: asyncio event-loop based tests.")
    for name in LEGACY_MARKERS:
        config.addinivalue_line("markers", f"{name}: auto-registered legacy mark")


def pytest_configure(config):  # type: ignore[no-untyped-def]
    _register_markers(config)


def _normalize(path: object) -> str:
    return os.path.relpath(str(path), _ROOT)


def pytest_ignore_collect(path, config):  # type: ignore[no-untyped-def]
    del config  # unused
    normalized = str(path).replace("\\", "/")
    if any(segment in normalized for segment in _IGNORED_SEGMENTS):
        return True
    candidate = Path(str(path))
    rel = candidate
    try:
        rel = candidate.resolve().relative_to(_ROOT)
    except Exception:
        rel = Path(_normalize(candidate))
    rel_posix = rel.as_posix()
    if candidate.is_dir():
        if rel_posix in _ALLOWED_DIRECTORIES:
            return False
        for allowed in _ALLOWED_RELATIVE_TESTS:
            if allowed.startswith(f"{rel_posix}/"):
                return False
        return True
    return rel_posix not in _ALLOWED_RELATIVE_TESTS


def pytest_sessionstart(session):  # type: ignore[no-untyped-def]
    seen: set[str] = set()
    duplicates: list[str] = []
    for entry in sys.path:
        if not isinstance(entry, str):
            continue
        normalized = os.path.abspath(entry)
        if normalized in seen:
            duplicates.append(normalized)
        else:
            seen.add(normalized)
    session.config._phase6_duplicate_sys_path = tuple(duplicates)  # type: ignore[attr-defined]


__all__ = ["DeterministicClock", "clock"]
