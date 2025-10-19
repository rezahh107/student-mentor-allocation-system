from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict

from .clock import Clock
from .io_utils import atomic_write, ensure_crlf


@dataclass(slots=True)
class DebugBundle:
    path: pathlib.Path
    clock: Clock
    _data: Dict[str, Any] = field(default_factory=dict)

    def record(self, key: str, value: Any) -> None:
        self._data[key] = {
            "timestamp": self.clock.now().isoformat(),
            "value": value,
        }

    def flush(self) -> None:
        atomic_write(self.path, ensure_crlf(json.dumps(self._data, ensure_ascii=False, indent=2)), newline="\n")
