from __future__ import annotations

import json
import os
import pathlib
import uuid
from dataclasses import dataclass
from typing import Any, Dict

from .clock import Clock
from .io_utils import atomic_write, ensure_crlf


@dataclass(slots=True)
class JsonLogger:
    path: pathlib.Path
    clock: Clock
    correlation_id: str | None = None
    _buffer: list[dict[str, Any]] = None  # type: ignore

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._buffer is None:
            self._buffer = []
        if self.correlation_id is None:
            self.correlation_id = uuid.uuid4().hex

    # ------------------------------------------------------------------
    def log(self, level: str, message: str, **context: Any) -> None:
        safe_context: Dict[str, Any] = {}
        for key, value in context.items():
            if isinstance(value, str) and "token" in key.lower():
                safe_context[key] = "***masked***"
            else:
                safe_context[key] = value
        record = {
            "timestamp": self.clock.now().isoformat(),
            "level": level.upper(),
            "message": message,
            "rid": self.correlation_id,
            "context": safe_context,
        }
        self._buffer.append(record)

    def info(self, message: str, **context: Any) -> None:
        self.log("INFO", message, **context)

    def warning(self, message: str, **context: Any) -> None:
        self.log("WARNING", message, **context)

    def error(self, message: str, **context: Any) -> None:
        self.log("ERROR", message, **context)

    # ------------------------------------------------------------------
    def flush(self) -> None:
        if not self._buffer:
            return
        lines = "\n".join(json.dumps(entry, ensure_ascii=False) for entry in self._buffer)
        atomic_write(self.path, ensure_crlf(lines), newline="\n")
        self._buffer.clear()


__all__ = ["JsonLogger"]
