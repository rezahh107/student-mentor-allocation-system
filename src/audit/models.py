"""Database schema for audit events."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer,
    DateTime,
    Enum,
    Index,
    MetaData,
    String,
    event,
    text,
)
from typing import Any


def _metadata() -> MetaData:
    return MetaData(schema=None)


try:  # SQLAlchemy 2.x style declarative base
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback for SQLAlchemy < 2.0
    from sqlalchemy import Column
    from sqlalchemy.orm import declarative_base

    mapped_column = Column  # type: ignore[assignment]

    try:  # SQLAlchemy 1.4 exposes ``Mapped``
        from sqlalchemy.orm import Mapped  # type: ignore[assignment]
    except ImportError:  # pragma: no cover - SQLAlchemy <=1.3
        from typing import Any as Mapped  # type: ignore[assignment]

    Base = declarative_base(metadata=_metadata())
else:

    class Base(DeclarativeBase):
        metadata = _metadata()

from .enums import AuditAction, AuditActorRole, AuditOutcome


class AuditEvent(Base):
    """ORM model mapped to the append-only audit_events table."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_role: Mapped[AuditActorRole] = mapped_column(Enum(AuditActorRole), nullable=False)
    center_scope: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    job_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[AuditOutcome] = mapped_column(Enum(AuditOutcome), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artifact_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_audit_events_ts_action", "ts", "action"),
        Index("ix_audit_events_actor_center_ts", "actor_role", "center_scope", "ts"),
        {"sqlite_autoincrement": True},
    )


@event.listens_for(AuditEvent.__table__, "after_create")
def _install_append_only_triggers(target, connection, **_: object) -> None:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.exec_driver_sql(
            """
            CREATE TRIGGER audit_events_no_update
            AFTER UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
            END;
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER audit_events_no_delete
            AFTER DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
            END;
            """
        )
    elif dialect == "postgresql":  # pragma: no cover - exercised in integration env
        connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION audit_events_guard()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'AUDIT_APPEND_ONLY';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_guard();
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_guard();
            """
        )
    else:  # pragma: no cover - rare dialects
        connection.exec_driver_sql(
            text(
                "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='AUDIT_APPEND_ONLY'; END;"
            )
        )
        connection.exec_driver_sql(
            text(
                "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='AUDIT_APPEND_ONLY'; END;"
            )
        )


__all__ = ["Base", "AuditEvent"]
