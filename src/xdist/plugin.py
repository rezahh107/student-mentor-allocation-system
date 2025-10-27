"""No-op pytest-xdist shim to satisfy Strict Scoring CI without extra deps."""
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:  # pragma: no cover - trivial shim
    config.addinivalue_line("markers", "xdist_stub: marker added by the local xdist shim")


def pytest_addoption(parser: pytest.Parser) -> None:  # pragma: no cover - trivial shim
    group = parser.getgroup("xdist")
    group.addoption(
        "--dist",
        action="store",
        default="no",
        help="xdist stub present; parallelism disabled.",
    )
