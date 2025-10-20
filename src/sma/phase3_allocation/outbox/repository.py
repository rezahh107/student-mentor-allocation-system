"""Persistence helpers for outbox events."""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sma.infrastructure.persistence.models import OutboxMessageModel

from .clock import Clock
from .models import OutboxEvent, OutboxMessage


class OutboxRepository:
    """Repository for accessing outbox rows inside a transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    def add(self, event: OutboxEvent) -> None:
        model = event.to_model()
        try:
            self._session.add(model)
        except IntegrityError as exc:  # pragma: no cover - defensive guard
            raise ValueError("DUPLICATE_EVENT|رویداد تکراری است") from exc

    def list_due_for_update(
        self,
        *,
        clock: Clock,
        limit: int,
    ) -> Sequence[OutboxMessage]:
        now = clock.now()
        stmt = (
            select(OutboxMessageModel)
            .where(
                OutboxMessageModel.status == "PENDING",
                OutboxMessageModel.available_at <= now,
            )
            .order_by(OutboxMessageModel.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = self._session.execute(stmt)
        return [OutboxMessage(model=row[0]) for row in result]

    def flush(self) -> None:
        self._session.flush()
