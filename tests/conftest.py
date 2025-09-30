import os

os.environ.setdefault("RUN_PERFORMANCE_SUITE", "1")

pytest_plugins = [
    "tests.audit_retention.conftest",
    "tests.auth.conftest",
    "tests.fixtures.state",
    "tests.fixtures.debug_context",
    "tests.ops.conftest",
    "tests.plugins.pytest_asyncio_compat",
    "tests.plugins.session_stats",
    "tests.uploads.conftest",
    "pytester",
]

__all__ = ["pytest_plugins"]
