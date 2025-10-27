"""State management helpers for deterministic tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class InMemoryStore:
    """A simple namespace-aware key/value store.

    Attributes:
        namespace: Prefix namespace applied to stored keys.
        _data: Internal dictionary maintaining the key/value pairs.
    """

    namespace: str
    _data: Dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str) -> None:
        """Store a value under the provided key.

        Args:
            key: Logical identifier without namespace prefix.
            value: Serialised value associated with the key.
        """

        self._data[f"{self.namespace}:{key}"] = value

    def get(self, key: str) -> str | None:
        """Retrieve a value for the given key if present.

        Args:
            key: Logical identifier without namespace prefix.

        Returns:
            Stored value when present, otherwise ``None``.
        """

        return self._data.get(f"{self.namespace}:{key}")

    def delete(self, key: str) -> None:
        """Remove the given key from the store if it exists.

        Args:
            key: Logical identifier without namespace prefix.
        """

        self._data.pop(f"{self.namespace}:{key}", None)

    def keys(self) -> list[str]:
        """Return a list of stored keys including the namespace prefix.

        Returns:
            List of fully qualified key names.
        """

        return list(self._data.keys())

    def flush(self) -> None:
        """Remove all stored entries."""

        self._data.clear()


__all__ = ["InMemoryStore"]
