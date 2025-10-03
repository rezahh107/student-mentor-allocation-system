"""Root-level pytest configuration for shared CI expectations."""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, NamedTuple
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
    "tests/retry/test_retry_jitter_determinism.py",
    "tests/retry/test_retry_metrics.py",
    "tests/exports/test_csv_excel_safety.py",
    "tests/exports/test_crlf_and_bom.py",
    "tests/exports/test_atomic_finalize.py",
    "tests/exports/test_streaming_perf.py",
    "tests/exports/test_signed_url.py",
    "tests/mw/test_export_middleware_order.py",
    "tests/ci/test_state_hygiene.py",
    "tests/obs/test_retry_metrics.py",
)

_ALLOWED_DIRECTORIES = {
    "tests",
    "tests/excel",
    "tests/domain",
    "tests/api",
    "tests/downloads",
}

_DEFAULT_TZ = ZoneInfo("Asia/Tehran")
_DEFAULT_START = datetime(2024, 1, 1, 0, 0, tzinfo=_DEFAULT_TZ)
_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _ROOT / "src"
_CLOCK_ALLOWLIST = {(_SRC_ROOT / "core" / "clock.py").resolve()}
_SCAN_DIRECTORIES = [(_SRC_ROOT / "phase6_import_to_sabt").resolve()]


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    parser.addini("env", "Environment variables for tests", type="linelist")
    parser.addini("qt_api", "Qt backend placeholder", default="")
    parser.addini("qt_no_exception_capture", "pytest-qt exception capture", type="bool", default=False)
    parser.addini("qt_wait_signal_raising", "pytest-qt wait signal raising", type="bool", default=False)
    parser.addini("timeout", "pytest-timeout default", default="0")
    parser.addini("timeout_func_only", "pytest-timeout scope", type="bool", default=False)
    parser.addini("xdist_strict", "pytest-xdist strict scheduling", type="bool", default=False)


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


def pytest_ignore_collect(collection_path, config):  # type: ignore[no-untyped-def]
    del config  # unused
    path = Path(collection_path)
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
    if rel.parent.as_posix() in _ALLOWED_DIRECTORIES:
        return False
    return rel_posix not in _ALLOWED_RELATIVE_TESTS


class _ImportsSnapshot(NamedTuple):
    datetime_aliases: frozenset[str]
    time_aliases: frozenset[str]
    zoneinfo_module_aliases: frozenset[str]
    zoneinfo_class_aliases: frozenset[str]


def _record_duplicate_sys_path(session) -> None:  # type: ignore[no-untyped-def]
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


def _collect_time_aliases(tree: ast.AST) -> _ImportsSnapshot:
    datetime_aliases: set[str] = {"datetime"}
    time_aliases: set[str] = {"time"}
    zoneinfo_module_aliases: set[str] = {"zoneinfo"}
    zoneinfo_class_aliases: set[str] = set()

    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "datetime":
                for alias in node.names:
                    if alias.name == "datetime":
                        datetime_aliases.add(alias.asname or alias.name)
            elif module == "time":
                for alias in node.names:
                    if alias.name == "time":
                        time_aliases.add(alias.asname or alias.name)
            elif module == "zoneinfo":
                for alias in node.names:
                    if alias.name == "ZoneInfo":
                        zoneinfo_class_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.asname or alias.name
                if alias.name == "datetime":
                    datetime_aliases.add(target)
                elif alias.name == "time":
                    time_aliases.add(target)
                elif alias.name == "zoneinfo":
                    zoneinfo_module_aliases.add(target)

    return _ImportsSnapshot(
        datetime_aliases=frozenset(datetime_aliases),
        time_aliases=frozenset(time_aliases),
        zoneinfo_module_aliases=frozenset(zoneinfo_module_aliases),
        zoneinfo_class_aliases=frozenset(zoneinfo_class_aliases),
    )


def _resolve_dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _detect_wall_clock_usage(path: Path, tree: ast.AST, snapshot: _ImportsSnapshot) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            dotted = _resolve_dotted_name(func)
            if dotted is not None:
                head, _, attr = dotted.partition(".")
                if attr in {"now", "utcnow", "today"} and head in snapshot.datetime_aliases:
                    violations.append(f"{path}:{node.lineno}:{dotted}")
                elif attr == "time" and head in snapshot.time_aliases:
                    violations.append(f"{path}:{node.lineno}:{dotted}")
                elif attr == "ZoneInfo" and head in snapshot.zoneinfo_module_aliases:
                    violations.append(f"{path}:{node.lineno}:{dotted}")
            if isinstance(func, ast.Name) and func.id in snapshot.zoneinfo_class_aliases:
                violations.append(f"{path}:{node.lineno}:{func.id}")
    return violations


def _run_wall_clock_guard() -> Dict[str, tuple[str, ...]]:
    scanned: list[str] = []
    failures: list[str] = []
    if not _SRC_ROOT.exists():
        return {"scanned": tuple(), "banned": tuple()}
    for base in _SCAN_DIRECTORIES:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            resolved = path.resolve()
            if resolved in _CLOCK_ALLOWLIST:
                continue
            scanned.append(str(path))
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:  # pragma: no cover - invalid sources should not occur
                failures.append(f"{path}:{exc.lineno}:syntax-error")
                continue
            snapshot = _collect_time_aliases(tree)
            failures.extend(_detect_wall_clock_usage(path, tree, snapshot))
    return {"scanned": tuple(scanned), "banned": tuple(sorted(failures))}


def pytest_sessionstart(session):  # type: ignore[no-untyped-def]
    _record_duplicate_sys_path(session)
    guard_payload = _run_wall_clock_guard()
    session.config._repo_wall_clock_guard = guard_payload  # type: ignore[attr-defined]
    banned = guard_payload.get("banned", ())
    if banned:
        message = (
            "TIME_SOURCE_FORBIDDEN: «استفادهٔ مستقیم از زمان سیستم مجاز نیست؛ از Clock تزریق‌شده استفاده کنید.» "
            + ", ".join(banned)
        )
        raise pytest.UsageError(message)


__all__ = ["DeterministicClock", "clock"]
