from __future__ import annotations

import base64
import hmac
import base64
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, MutableMapping
from urllib.parse import parse_qs, urlparse

from binascii import Error as Base64Error

from sma.phase6_import_to_sabt.models import SignedURLProvider
from sma.phase6_import_to_sabt.security.config import SigningKeyDefinition


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
    token_id: str
    kid: str
    expires: int
    signature: str

    def as_query(self) -> Mapping[str, str]:
        expiry_text = str(self.expires)
        return {
            "signed": self.token_id,
            "token": self.token_id,
            "kid": self.kid,
            "exp": expiry_text,
            "expires": expiry_text,
            "signature": self.signature,
            "sig": self.signature,
        }

    @property
    def signed(self) -> str:
        return self.token_id

    @property
    def exp(self) -> int:
        return self.expires

    @property
    def sig(self) -> str:
        return self.signature


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
        return {
            kid
            for kid, definition in self._definitions.items()
            if definition.state in {"active", "next", "retired"}
        }


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
        return SignedURLComponents(
            path=normalized_path,
            token_id=encoded_path,
            kid=active.kid,
            expires=expires_at,
            signature=signature,
        )

    def sign(self, file_path: str, expires_in: int = 3600) -> str:
        components = self.issue(file_path, ttl_seconds=expires_in)
        return (
            f"{self._base_path}/{components.token_id}?signature={components.signature}"
            f"&expires={components.expires}&kid={components.kid}"
        )

    def verify_components(
        self,
        *,
        token_id: str | None = None,
        token: str | None = None,
        signed: str | None = None,
        kid: str | None = None,
        expires: int | None = None,
        exp: int | None = None,
        signature: str | None = None,
        sig: str | None = None,
        now: datetime | None = None,
    ) -> str:
        token_value = token_id or token or signed
        if token_value is None:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            raise SignatureError("توکن نامعتبر است.", reason="missing_token")
        if not kid:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            raise SignatureError("توکن نامعتبر است.", reason="missing_kid")
        expiry_value = expires if expires is not None else exp
        if expiry_value is None:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            raise SignatureError("توکن نامعتبر است.", reason="missing_expiry")
        signature_value = signature or sig
        if signature_value is None:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            raise SignatureError("توکن نامعتبر است.", reason="missing_signature")
        try:
            path = self._decode_path(token_value)
        except SignatureError as exc:
            self._metrics.download_signed_total.labels(outcome=exc.reason).inc()
            raise
        now_ts = int((now or self._clock.now()).timestamp())
        if expiry_value <= now_ts:
            self._metrics.download_signed_total.labels(outcome="expired").inc()
            raise SignatureError("لینک دانلود منقضی شده است.", reason="expired")
        if kid not in self._keys.allowed_for_verification():
            self._metrics.download_signed_total.labels(outcome="unknown_kid").inc()
            raise SignatureError("کلید امضا ناشناخته است.", reason="unknown_kid")
        key = self._keys.get(kid)
        if key is None:
            self._metrics.download_signed_total.labels(outcome="unknown_kid").inc()
            raise SignatureError("کلید امضا ناشناخته است.", reason="unknown_kid")
        canonical = self._canonical("GET", path, {}, expiry_value)
        expected = self._sign(key.secret, canonical)
        if not hmac.compare_digest(expected, signature_value):
            self._metrics.download_signed_total.labels(outcome="forged").inc()
            raise SignatureError("توکن نامعتبر است.", reason="signature")
        self._metrics.download_signed_total.labels(outcome="ok").inc()
        return path

    def verify(self, url: str, *, now: datetime | None = None) -> bool:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        token_id = query.get("signed", [None])[0] or query.get("token", [None])[0]
        kid = query.get("kid", [None])[0]
        expires_text = query.get("expires", [None])[0] or query.get("exp", [None])[0]
        sig = query.get("signature", [None])[0] or query.get("sig", [None])[0]
        if not token_id or not kid or not expires_text or not sig:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            return False
        try:
            expires = int(expires_text)
        except ValueError:
            self._metrics.download_signed_total.labels(outcome="malformed").inc()
            return False
        try:
            self.verify_components(token_id=token_id, kid=kid, expires=expires, sig=sig, now=now)
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
        try:
            raw = base64.urlsafe_b64decode(value + padding)
        except (Base64Error, ValueError) as exc:  # pragma: no cover - defensive
            raise SignatureError("توکن نامعتبر است.", reason="token_decode") from exc
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - defensive
            raise SignatureError("توکن نامعتبر است.", reason="token_decode") from exc
        return DualKeySigner._normalize_path(decoded)


__all__ = ["DualKeySigner", "SignatureError", "SignedURLComponents", "SigningKeySet"]

