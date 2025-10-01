"""Observability test config (no local pytest_plugins; see tests/conftest.py)."""

from __future__ import annotations


def pytest_configure(config):  # type: ignore[no-untyped-def]
    config.addinivalue_line(
        "markers",
        "asyncio: آزمون‌های مبتنی بر حلقهٔ رویداد asyncio.",
    )
