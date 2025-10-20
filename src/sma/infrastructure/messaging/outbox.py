# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Iterable

from sma.domain.shared.events import DomainEvent


class InMemoryOutbox:
    """Simple in-memory outbox placeholder for Phase 1 design/testing."""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []

    def enqueue(self, *events: DomainEvent) -> None:
        self._events.extend(events)

    def drain(self) -> list[DomainEvent]:
        ev = list(self._events)
        self._events.clear()
        return ev

