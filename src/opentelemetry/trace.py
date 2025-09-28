"""Minimal trace API stub used in tests when opentelemetry is unavailable."""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Span:
    name: str
    kind: str | None = None
    attributes: dict[str, object] | None = None
    start_time: float = time.time()

    def set_attribute(self, key: str, value: object) -> None:
        if self.attributes is None:
            self.attributes = {}
        self.attributes[key] = value

    def end(self) -> None:  # pragma: no cover - noop
        return None


class _Tracer:
    def start_span(
        self,
        name: str,
        *,
        kind: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> Span:
        return Span(name=name, kind=kind, attributes=dict(attributes or {}))


def get_tracer(_name: str) -> _Tracer:
    return _Tracer()


class SpanKind:
    SERVER = "SERVER"


__all__ = ["Span", "SpanKind", "get_tracer"]
