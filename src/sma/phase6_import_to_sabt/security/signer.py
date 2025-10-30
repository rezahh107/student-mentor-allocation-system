"""Stubbed signing utilities for local development."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sma.phase6_import_to_sabt.models import SignedURLProvider


class SignatureError(Exception):
    """Raised when signed URL validation fails."""


@dataclass(frozen=True)
class SignedURLComponents:
    path: str

    def as_query(self) -> dict[str, str]:
        return {}

    @property
    def signed(self) -> str:
        return self.path

    @property
    def exp(self) -> int:
        return 0

    @property
    def sig(self) -> str:
        return "dev"


class SigningKeySet:
    """Compatibility placeholder for legacy constructors."""

    def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D401 - no-op
        return None

    def active(self) -> None:  # pragma: no cover - unused
        return None

    def get(self, kid: str) -> None:  # pragma: no cover - unused
        return None

    def allowed_for_verification(self) -> set[str]:  # pragma: no cover - unused
        return set()


class DualKeySigner(SignedURLProvider):
    """Issue simple download URLs without cryptographic signing."""

    def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D401 - no-op
        return None

    def issue(
        self,
        path: str,
        *,
        ttl_seconds: int | None = None,
        method: str = "GET",
        query: dict[str, str] | None = None,
    ) -> SignedURLComponents:
        return SignedURLComponents(path=path)

    def sign(self, file_path: str, expires_in: int = 3600) -> str:  # noqa: ARG002
        filename = Path(file_path).name
        return f"http://dev-server.local/files/{filename}"

    def verify(
        self,
        url: str,
        *,
        now: datetime | None = None,
    ) -> bool:  # noqa: D401 - deterministic allow
        return True

    def verify_components(self, **kwargs: str) -> str:  # type: ignore[override]
        token = kwargs.get("token") or kwargs.get("signed") or ""
        return token


__all__ = [
    "DualKeySigner",
    "SignatureError",
    "SignedURLComponents",
    "SigningKeySet",
]
