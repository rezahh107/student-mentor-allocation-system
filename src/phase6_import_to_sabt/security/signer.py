from __future__ import annotations

import base64
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, MutableMapping
from urllib.parse import parse_qs, urlparse

from phase6_import_to_sabt.models import SignedURLProvider
from phase6_import_to_sabt.security.config import SigningKeyDefinition


logger = logging.getLogger(__name__)


class SignatureError(Exception):
    """Raised when signed URL validation fails."""

    def __init__(self, message_fa: str, *, reason: str) -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.reason = reason


@dataclass(frozen=True)
class SignedURLComponents:
    path: str
    signed: str
    kid: str
    exp: int
    sig: str

    def as_query(self) -> Mapping[str, str]:
        return {"signed": self.signed, "kid": self.kid, "exp": str(self.exp), "sig": self.sig}


class SigningKeySet:
    """Store active and next signing keys for dual rotation."""

    def __init__(self, definitions: Iterable[SigningKeyDefinition]) -> None:
        self._definitions: MutableMapping[str, SigningKeyDefinition] = {item.kid: item for item in definitions}

    def active(self) -> SigningKeyDefinition:
        for definition in self._definitions.values():
            if definition.state == "active":
                return definition
        raise KeyError("no-active-key")

    def get(self, kid: str) -> SigningKeyDefinition | None:
        return self._definitions.get(kid)

    def allowed_for_verification(self) -> set[str]:
        return {kid for kid, definition in self._definitions.items() if definition.state in {"active", "next"}}


class DualKeySigner(SignedURLProvider):
    """Generate and verify download URLs using dual rotating keys."""

    def __init__(
        self,
        *,
        keys: SigningKeySet,
        clock,
        metrics,
        default_ttl_seconds: int,
        base_path: str = "/download",
    ) -> None:
        self._keys = keys
        self._clock = clock
        self._metrics = metrics
        self._default_ttl = default_ttl_seconds
        self._base_path = base_path.rstrip("/") or "/download"
        self._debug = os.getenv("DEBUG_SIG") == "1"

    def issue(
        self,
        path: str,
        *,
        ttl_seconds: int | None = None,
        method: str = "GET",
        query: Mapping[str, str] | None = None,
    ) -> SignedURLComponents:
        normalized_path = self._normalize_path(path)
        expires_in = ttl_seconds or self._default_ttl
        expires_at = int(self._clock.now().timestamp()) + max(1, int(expires_in))
        active = self._keys.active()
        canonical = self._canonical(method, normalized_path, query or {}, expires_at)
        signature = self._sign(active.secret, canonical)
        encoded_path = base64.urlsafe_b64encode(normalized_path.encode("utf-8")).decode("utf-8").rstrip("=")
        self._metrics.download_signed_total.labels(outcome="issued").inc()
        return SignedURLComponents(path=normalized_path, signed=encoded_path, kid=active.kid, exp=expires_at, sig=signature)

    def sign(self, file_path: str, expires_in: int = 3600) -> str:
        components = self.issue(file_path, ttl_seconds=expires_in)
        return (
            f"{self._base_path}?signed={components.signed}&kid={components.kid}"
            f"&exp={components.exp}&sig={components.sig}"
        )

    def verify_components(
        self,
        *,
        signed: str,
        kid: str,
        exp: int,
        sig: str,
        now: datetime | None = None,
    ) -> str:
        try:
            path = self._decode_path(signed)
        except SignatureError as exc:
            self._metrics.download_signed_total.labels(outcome=exc.reason).inc()
            raise
        now_ts = int((now or self._clock.now()).timestamp())
        if exp <= now_ts:
            self._metrics.download_signed_total.labels(outcome="expired").inc()
            raise SignatureError("لینک دانلود منقضی شده است.", reason="expired")
        if kid not in self._keys.allowed_for_verification():
            self._metrics.download_signed_total.labels(outcome="unknown_kid").inc()
            raise SignatureError("کلید امضا ناشناخته است.", reason="unknown_kid")
        key = self._keys.get(kid)
        if key is None:
            self._metrics.download_signed_total.labels(outcome="unknown_kid").inc()
            raise SignatureError("کلید امضا ناشناخته است.", reason="unknown_kid")
        canonical = self._canonical("GET", path, {}, exp)
        expected = self._sign(key.secret, canonical)
        if not hmac.compare_digest(expected, sig):
            self._metrics.download_signed_total.labels(outcome="forged").inc()
            raise SignatureError("توکن نامعتبر است.", reason="signature")
        self._metrics.download_signed_total.labels(outcome="ok").inc()
        return path

    def verify(self, url: str, *, now: datetime | None = None) -> bool:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        signed = query.get("signed", [None])[0]
        kid = query.get("kid", [None])[0]
        exp_text = query.get("exp", [None])[0]
        sig = query.get("sig", [None])[0]
        if not signed or not kid or not exp_text or not sig:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            return False
        try:
            exp = int(exp_text)
        except ValueError:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            return False
        try:
            self.verify_components(signed=signed, kid=kid, exp=exp, sig=sig, now=now)
        except SignatureError:
            return False
        return True

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        if normalized.startswith("../") or "../" in normalized:
            raise SignatureError("توکن نامعتبر است.", reason="path_traversal")
        return normalized

    def _canonical(
        self,
        method: str,
        path: str,
        query: Mapping[str, str],
        exp: int,
    ) -> bytes:
        query_text = "&".join(f"{key}={value}" for key, value in sorted(query.items()))
        canonical = f"{method.upper()}\n{path}\n{query_text}\n{exp}"
        if self._debug:
            logger.debug(
                "download.signature.canonical",
                extra={"canonical": canonical, "kid": query.get("kid")},
            )
        return canonical.encode("utf-8")

    @staticmethod
    def _sign(secret: str, canonical: bytes) -> str:
        digest = hmac.new(secret.encode("utf-8"), canonical, "sha256").digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    @staticmethod
    def _decode_path(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode("utf-8")
        return DualKeySigner._normalize_path(decoded)


__all__ = ["DualKeySigner", "SignatureError", "SignedURLComponents", "SigningKeySet"]

