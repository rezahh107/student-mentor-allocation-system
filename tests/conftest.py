"""Root-level pytest config for CI and shared markers.
Do NOT import suite-specific plugins here (prevents cross-suite deps)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
import sqlalchemy.orm as sa_orm
from sqlalchemy.pool import StaticPool

pytest_plugins = (
    "pytest_asyncio.plugin",
    "tests.plugins.pytest_asyncio_compat",
    "tests._compat.pytest_asyncio_scope",
)


Session = sa_orm.Session
sessionmaker = sa_orm.sessionmaker


if hasattr(sa_orm, "DeclarativeBase"):

    class TestDeclarativeBase(sa_orm.DeclarativeBase):
        """Minimal SQLAlchemy declarative base for in-memory integration tests."""


else:
    TestDeclarativeBase = sa_orm.declarative_base()  # type: ignore[misc]


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Provide an in-memory SQLite engine aligned with SQLAlchemy 2.x APIs."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    TestDeclarativeBase.metadata.create_all(engine)
    try:
        yield engine
    finally:
        TestDeclarativeBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:  # type: ignore[override]
    """Create an isolated SQLAlchemy session per-test with rollback cleanup."""

    connection = db_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.flush()
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def integration_context():
    """Expose the shared integration context with deterministic cleanup."""

    from tests.helpers.integration_context import IntegrationContext

    context = IntegrationContext().setup()
    try:
        yield context
    finally:
        context.teardown()


@pytest.fixture(scope="session")
def large_dataset():
    """Provide a deterministic 10k-row dataset for Excel safety checks."""

    from tests.helpers.integration_context import create_large_dataset

    return create_large_dataset()


@pytest.fixture(scope="session")
def persian_dataset():
    """Provide a curated Persian-language dataset with tricky edge cases."""

    from tests.helpers.integration_context import create_persian_dataset

    return create_persian_dataset()


@pytest.fixture
def temp_excel_dir(tmp_path_factory: pytest.TempPathFactory, integration_context):
    """Create a unique workspace per test for exporter artifacts (with cleanup)."""

    temp_dir = tmp_path_factory.mktemp(
        f"excel-{integration_context.namespace.replace(':', '-')}", numbered=True
    )
    try:
        yield temp_dir
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    parser.addini("asyncio_mode", "Default asyncio mode for pytest-asyncio", default="auto")


def pytest_configure(config):  # type: ignore[no-untyped-def]
    # Shared, harmless markers only:
    config.addinivalue_line("markers", "asyncio: asyncio event-loop based tests.")
