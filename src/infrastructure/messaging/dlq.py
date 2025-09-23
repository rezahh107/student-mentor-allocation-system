# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List

from src.domain.shared.events import DomainEvent


class InMemoryDLQ:
    def __init__(self) -> None:
        self._events: List[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self._events.append(event)

    def drain(self) -> list[DomainEvent]:
        out = list(self._events)
        self._events.clear()
        return out

