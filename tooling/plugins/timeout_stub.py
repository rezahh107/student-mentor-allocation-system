from __future__ import annotations

"""Pytest-timeout shim exposing ini options when plugin missing."""

try:  # pragma: no cover
    import pytest_timeout  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    PYTEST_TIMEOUT_PRESENT = False
else:  # pragma: no cover
    PYTEST_TIMEOUT_PRESENT = True


def pytest_addoption(parser):  # pragma: no cover - exercised via tests
    if PYTEST_TIMEOUT_PRESENT:
        return
    group = parser.getgroup("timeout")
    group.addoption(
        "--timeout",
        action="store",
        default=None,
        help="Set a per-test timeout (seconds).",
    )
    parser.addini("timeout", "Default per-test timeout")
    parser.addini("timeout_method", "Mechanism used to enforce timeouts", default="thread")


def pytest_configure(config):  # pragma: no cover - integration tested
    if PYTEST_TIMEOUT_PRESENT:
        return
    config.addinivalue_line("markers", "timeout_stub: registered for compatibility")
