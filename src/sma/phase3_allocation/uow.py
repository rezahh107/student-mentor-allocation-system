"""Unit of work abstractions for allocation workflows."""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable, Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class UnitOfWorkError(RuntimeError):
    """Wraps unexpected transactional errors."""


class UnitOfWork(AbstractContextManager):
    """Abstract unit-of-work contract."""

    session: Session

    def commit(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def rollback(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc:
                self.rollback()
            elif not getattr(self, "_skip_commit", False):
                self.commit()
        finally:
            self.close()
        return False


SessionFactory = Callable[[], Session]


@dataclass(slots=True)
class SQLAlchemyUnitOfWork(UnitOfWork):
    """SQLAlchemy-backed unit of work with explicit session factory."""

    session_factory: SessionFactory

    def __post_init__(self) -> None:
        self.session = self.session_factory()

    def commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover - thin wrapper
            self.session.rollback()
            raise UnitOfWorkError("COMMIT_FAILED") from exc

    def rollback(self) -> None:
        self._skip_commit = True
        self.session.rollback()

    def close(self) -> None:
        self.session.close()


class UnitOfWorkFactory(Protocol):
    """Factory protocol producing new unit of work instances."""

    def __call__(self) -> UnitOfWork:
        """Return a ready-to-use unit of work."""

