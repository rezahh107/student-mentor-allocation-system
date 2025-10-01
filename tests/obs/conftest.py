"""Load pytest-asyncio explicitly for observability suites."""

from __future__ import annotations

# pytest_plugins moved to tests/conftest.py


def pytest_configure(config):  # type: ignore[no-untyped-def]
    config.addinivalue_line("markers", "asyncio: آزمون‌های مبتنی بر حلقهٔ رویداد asyncio.")
