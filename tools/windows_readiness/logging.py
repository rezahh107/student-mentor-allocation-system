"""Structured JSON logging helper for readiness tooling."""

from __future__ import annotations

import json
from typing import Any, Mapping, MutableMapping

from .clock import DeterministicClock


class JsonLogger:
    """Minimal JSON logger emitting deterministic timestamps."""

    def __init__(self, stream, *, clock: DeterministicClock, correlation_id: str) -> None:
        self._stream = stream
        self._clock = clock
        self._cid = correlation_id

    def _payload(self, level: str, message: str, fields: Mapping[str, Any] | None) -> MutableMapping[str, Any]:
        payload: MutableMapping[str, Any] = {
            "ts": self._clock.iso(),
            "level": level,
            "message": message,
            "correlation_id": self._cid,
        }
        if fields:
            for key, value in fields.items():
                if value is None:
                    continue
                payload[key] = value
        return payload

    def _emit(self, level: str, message: str, **fields: Any) -> None:
        payload = self._payload(level, message, fields)
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()

    def info(self, message: str, **fields: Any) -> None:
        self._emit("INFO", message, **fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit("WARNING", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit("ERROR", message, **fields)


__all__ = ["JsonLogger"]

