from __future__ import annotations

from typing import Dict, Iterable, List


class FakeLDAPDirectory:
    def __init__(self, mapping: Dict[str, Iterable[str]]) -> None:
        self._mapping = {key: list(value) for key, value in mapping.items()}

    async def fetch_groups(self, user: str) -> List[str]:
        return list(self._mapping.get(user, []))


__all__ = ["FakeLDAPDirectory"]
