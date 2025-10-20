"""Minimal trace API stub used in tests when opentelemetry is unavailable."""
from __future__ import annotations

from dataclasses import dataclass, field

from sma.core.clock import Clock


@dataclass
class Span:
    name: str
    kind: str | None = None
    attributes: dict[str, object] | None = None
    clock: Clock = field(default_factory=Clock.for_tehran)
    start_time: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_time", self.clock.unix_timestamp())

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
