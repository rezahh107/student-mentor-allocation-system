from __future__ import annotations

"""Pytest-xdist compatibility shim for environments without the plugin."""

from typing import Any

try:  # pragma: no cover - exercised when plugin installed
    import xdist.plugin  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - runtime branch
    xdist = None
else:  # pragma: no cover
    xdist = xdist.plugin


STUB_ENABLED = xdist is None
STUB_ACTIVE = STUB_ENABLED


__all__ = [
    "pytest_addoption",
    "pytest_configure",
    "STUB_ENABLED",
    "STUB_ACTIVE",
]


def pytest_addoption(parser):  # pragma: no cover - exercised via integration
    if not STUB_ENABLED:
        return
    group = parser.getgroup("xdist")
    group.addoption(
        "-n",
        "--numprocesses",
        action="store",
        dest="numprocesses",
        help="Run tests in parallel by specifying the number of workers.",
    )
    group.addoption(
        "--dist",
        action="store",
        dest="dist",
        default="loadscope",
        help="Distribution mode for xdist stub.",
    )


def pytest_configure(config):  # pragma: no cover - integration tested
    if not STUB_ENABLED:
        return
    config.addinivalue_line("markers", "xdist_stub: registered for compatibility")
