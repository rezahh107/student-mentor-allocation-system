from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(slots=True)
class BridgeSession:
    """Server-side representation of an authenticated SSO session."""

    sid: str
    role: Literal["ADMIN", "MANAGER"]
    center_scope: str
    issued_at: datetime
    expires_at: datetime

    @property
    def ttl_seconds(self) -> int:
        return max(0, int((self.expires_at - self.issued_at).total_seconds()))


__all__ = ["BridgeSession"]
