"""Async-style persistence for audit events backed by SQLAlchemy sessions."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .enums import AuditAction, AuditActorRole, AuditOutcome
from .models import AuditEvent, Base
from .retry import retry_async


@dataclass(slots=True)
class AuditEventCreate:
    ts: datetime
    actor_role: AuditActorRole
    center_scope: str | None
    action: AuditAction
    resource_type: str
    resource_id: str
    job_id: str | None
    request_id: str
    outcome: AuditOutcome
    error_code: str | None
    artifact_sha256: str | None


@dataclass(slots=True)
class AuditQuery:
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    actor_role: AuditActorRole | None = None
    action: AuditAction | None = None
    center_scope: str | None = None
    outcome: AuditOutcome | None = None
    limit: int | None = 200
    offset: int = 0


class AuditRepository:
    """Repository handling append-only persistence with deterministic retries."""

    def __init__(
        self,
        writer: Engine,
        *,
        replica: Engine | None = None,
        retry_attempts: int = 4,
        base_delay: float = 0.05,
    ) -> None:
        self._writer_engine = writer
        self._replica_engine = replica or writer
        self._writer_factory: sessionmaker[Session] = sessionmaker(bind=writer, expire_on_commit=False)
        self._reader_factory: sessionmaker[Session] = sessionmaker(bind=self._replica_engine, expire_on_commit=False)
        self._retry_attempts = retry_attempts
        self._base_delay = base_delay

    async def init(self) -> None:
        await asyncio.to_thread(Base.metadata.create_all, self._writer_engine)

    async def insert(self, payload: AuditEventCreate, *, rid: str) -> int:
        def _sync_insert() -> int:
            with self._writer_factory() as session:
                data = asdict(payload)
                event = AuditEvent(**data)
                session.add(event)
                session.flush()
                event_id = event.id
                session.commit()
                return event_id

        async def _op() -> int:
            return await asyncio.to_thread(_sync_insert)

        return await retry_async(
            _op,
            attempts=self._retry_attempts,
            base_delay=self._base_delay,
            rid=rid,
            retry_exceptions=(OperationalError, DBAPIError),
        )

    async def fetch_one(self, event_id: int) -> AuditEvent | None:
        def _sync_fetch() -> AuditEvent | None:
            with self._reader_factory() as session:
                return session.get(AuditEvent, event_id)

        return await asyncio.to_thread(_sync_fetch)

    async def fetch_many(self, query: AuditQuery) -> list[AuditEvent]:
        def _sync_fetch() -> list[AuditEvent]:
            with self._reader_factory() as session:
                stmt = select(AuditEvent).order_by(AuditEvent.ts.desc())
                if query.from_ts is not None:
                    stmt = stmt.where(AuditEvent.ts >= query.from_ts)
                if query.to_ts is not None:
                    stmt = stmt.where(AuditEvent.ts <= query.to_ts)
                if query.actor_role is not None:
                    stmt = stmt.where(AuditEvent.actor_role == query.actor_role)
                if query.action is not None:
                    stmt = stmt.where(AuditEvent.action == query.action)
                if query.center_scope is not None:
                    stmt = stmt.where(AuditEvent.center_scope == query.center_scope)
                if query.outcome is not None:
                    stmt = stmt.where(AuditEvent.outcome == query.outcome)
                if query.limit is not None:
                    stmt = stmt.limit(query.limit)
                if query.offset:
                    stmt = stmt.offset(query.offset)
                result = session.execute(stmt)
                return list(result.scalars())

        return await asyncio.to_thread(_sync_fetch)

    async def stream(self, query: AuditQuery) -> AsyncIterator[AuditEvent]:
        def _sync_stream() -> list[AuditEvent]:
            with self._reader_factory() as session:
                stmt = select(AuditEvent).order_by(AuditEvent.ts.asc())
                filters = []
                if query.from_ts is not None:
                    filters.append(AuditEvent.ts >= query.from_ts)
                if query.to_ts is not None:
                    filters.append(AuditEvent.ts <= query.to_ts)
                if query.actor_role is not None:
                    filters.append(AuditEvent.actor_role == query.actor_role)
                if query.action is not None:
                    filters.append(AuditEvent.action == query.action)
                if query.center_scope is not None:
                    filters.append(AuditEvent.center_scope == query.center_scope)
                if query.outcome is not None:
                    filters.append(AuditEvent.outcome == query.outcome)
                if filters:
                    stmt = stmt.where(and_(*filters))
                result = session.execute(stmt)
                return list(result.scalars())

        events = await asyncio.to_thread(_sync_stream)
        for event in events:
            yield event


__all__ = ["AuditRepository", "AuditQuery", "AuditEventCreate"]
