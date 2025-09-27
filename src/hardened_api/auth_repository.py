"""API key repository primitives with expiry and revocation semantics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable


@dataclass(slots=True)
class APIKeyRecord:
    name: str
    key_hash: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, str | None]) -> "APIKeyRecord":
        expires = datetime.fromisoformat(row["expires_at"]) if row.get("expires_at") else None
        revoked = datetime.fromisoformat(row["revoked_at"]) if row.get("revoked_at") else None
        return cls(
            name=row["name"] or "anonymous",
            key_hash=row["key_hash"],
            expires_at=expires,
            revoked_at=revoked,
        )


class InMemoryAPIKeyRepository:
    """Simple in-memory repository used for tests and bootstrap."""

    def __init__(self, records: Iterable[APIKeyRecord]) -> None:
        self._records: Dict[str, APIKeyRecord] = {record.key_hash: record for record in records}

    async def is_active(self, hashed_key: str) -> bool:
        record = self._records.get(hashed_key)
        if not record:
            return False
        now = datetime.now(tz=timezone.utc)
        if record.expires_at and record.expires_at <= now:
            return False
        if record.revoked_at and record.revoked_at <= now:
            return False
        return True

    async def revoke(self, hashed_key: str) -> None:
        record = self._records.get(hashed_key)
        if record:
            record.revoked_at = datetime.now(tz=timezone.utc)

    def add(self, record: APIKeyRecord) -> None:
        self._records[record.key_hash] = record
