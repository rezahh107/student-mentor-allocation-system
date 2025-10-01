"""Root-level pytest config for CI and shared markers.
Do NOT import suite-specific plugins here (prevents cross-suite deps)."""

from __future__ import annotations

def pytest_configure(config):  # type: ignore[no-untyped-def]
    # Shared, harmless markers only:
    config.addinivalue_line("markers", "asyncio: asyncio event-loop based tests.")
