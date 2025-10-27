"""State management helpers for deterministic tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class InMemoryStore:
    """A simple namespace-aware key/value store."""

    namespace: str
    _data: Dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str) -> None:
        self._data[f"{self.namespace}:{key}"] = value

    def get(self, key: str) -> str | None:
        return self._data.get(f"{self.namespace}:{key}")

    def delete(self, key: str) -> None:
        self._data.pop(f"{self.namespace}:{key}", None)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def flush(self) -> None:
        self._data.clear()


__all__ = ["InMemoryStore"]
