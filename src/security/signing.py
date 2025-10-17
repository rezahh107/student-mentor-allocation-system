"""Key rotation and dual-key signing helpers for download URLs."""

from __future__ import annotations

import base64
import hmac
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable, Mapping, MutableMapping, Protocol, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

from phase6_import_to_sabt.security.config import SigningKeyDefinition

__all__ = [
    "SigningError",
    "VerificationError",
    "KeyRotationError",
    "SigningKey",
    "SignatureEnvelope",
    "KeyRing",
    "KeyRingSigner",
    "keyring_from_definitions",
]


class Clock(Protocol):
    """Protocol representing deterministic clocks used across the system."""

    def now(self) -> datetime:
        """Return current timezone-aware datetime."""


class _Counter(Protocol):
    def labels(self, **kwargs: str) -> "_Counter":  # pragma: no cover - protocol only
        ...

    def inc(self, value: float = 1.0) -> None:  # pragma: no cover - protocol only
        ...


class SigningError(Exception):
    """Base exception carrying a Persian error message for signing issues."""

    def __init__(self, message_fa: str, *, reason: str) -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.reason = reason


class VerificationError(SigningError):
    """Raised when signature verification fails."""


class KeyRotationError(SigningError):
    """Raised when key rotation cannot be completed."""


@dataclass(frozen=True)
class SigningKey:
    """Represents a signing key tracked inside the key ring."""

    kid: str
    secret: str
    state: str  # "active" or "retired"

    def as_definition(self) -> SigningKeyDefinition:
        state = "active" if self.state == "active" else "retired"
        return SigningKeyDefinition(self.kid, self.secret, state)


@dataclass(frozen=True)
class SignatureEnvelope:
    """Container describing the signed URL components."""

    path: str
    signed: str
    kid: str
    exp: int
    sig: str

    def as_query(self) -> Mapping[str, str]:
        return {"signed": self.signed, "kid": self.kid, "exp": str(self.exp), "sig": self.sig}


class KeyRing:
    """Manage active/retired signing keys with deterministic semantics."""

    def __init__(self, keys: Sequence[SigningKey]) -> None:
        if not keys:
            raise KeyRotationError("«هیچ کلید امضای فعالی یافت نشد.»", reason="empty")
        normalized: MutableMapping[str, SigningKey] = {}
        active_count = 0
        for key in keys:
            kid = _normalize_kid(key.kid)
            state = key.state if key.state in {"active", "retired"} else "retired"
            cleaned = SigningKey(kid=kid, secret=_normalize_secret(key.secret), state=state)
            normalized[kid] = cleaned
            if cleaned.state == "active":
                active_count += 1
        if active_count != 1:
            raise KeyRotationError("«پیکربندی کلیدها نامعتبر است؛ دقیقاً یک کلید باید فعال باشد.»", reason="active-count")
        self._keys = normalized

    def __iter__(self) -> Iterable[SigningKey]:
        return iter(self._keys.values())

    def active(self) -> SigningKey:
        for key in self._keys.values():
            if key.state == "active":
                return key
        raise KeyRotationError("«کلید فعال یافت نشد.»", reason="active-missing")

    def retired(self) -> tuple[SigningKey, ...]:
        return tuple(key for key in self._keys.values() if key.state == "retired")

    def verification_keys(self) -> tuple[SigningKey, ...]:
        return tuple(sorted(self._keys.values(), key=lambda item: (item.state != "active", item.kid)))

    def rotate(self, *, kid: str, secret: str) -> "KeyRing":
        kid = _normalize_kid(kid)
        secret = _normalize_secret(secret)
        if kid in self._keys and self._keys[kid].state == "active":
            raise KeyRotationError("«کلید جدید نمی‌تواند با کلید فعال فعلی هم‌نام باشد.»", reason="duplicate-active")
        updated: MutableMapping[str, SigningKey] = {}
        for existing in self._keys.values():
            state = "retired" if existing.state == "active" else existing.state
            updated[existing.kid] = SigningKey(existing.kid, existing.secret, state)
        updated[kid] = SigningKey(kid, secret, "active")
        return KeyRing(tuple(updated.values()))

    def as_definitions(self) -> tuple[SigningKeyDefinition, ...]:
        return tuple(key.as_definition() for key in self.verification_keys())


class KeyRingSigner:
    """Signing helper that supports dual-key verification with deterministic metrics."""

    def __init__(
        self,
        keyring: KeyRing,
        *,
        clock: Clock,
        default_ttl_seconds: int,
        counter: _Counter | None = None,
        base_path: str = "/download",
    ) -> None:
        self._keyring = keyring
        self._clock = clock
        self._ttl = max(60, int(default_ttl_seconds))
        self._counter = counter
        self._base_path = base_path.rstrip("/") or "/download"
        self._lock = threading.RLock()

    def issue(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, str] | None = None,
        ttl_seconds: int | None = None,
    ) -> SignatureEnvelope:
        normalized_path = _normalize_path(path)
        expires_at = _expiry(self._clock.now(), ttl_seconds or self._ttl)
        canonical = _canonical(method, normalized_path, query or {}, expires_at)
        with self._lock:
            active = self._keyring.active()
            signature = _sign(active.secret, canonical)
        encoded_path = _encode_path(normalized_path)
        self._record("issued")
        return SignatureEnvelope(path=normalized_path, signed=encoded_path, kid=active.kid, exp=expires_at, sig=signature)

    def signed_url(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, str] | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        envelope = self.issue(path, method=method, query=query, ttl_seconds=ttl_seconds)
        query_params = dict(query or {})
        query_params.update(envelope.as_query())
        return f"{self._base_path}?{urlencode(query_params)}"

    def verify(self, envelope: SignatureEnvelope) -> str:
        with self._lock:
            return self._verify(envelope)

    def verify_url(self, url: str) -> str:
        parts = urlsplit(url)
        payload = parse_qs(parts.query)
        signed = payload.get("signed", [""])[0]
        kid = payload.get("kid", [""])[0]
        exp_text = payload.get("exp", [""])[0]
        sig = payload.get("sig", [""])[0]
        if not signed or not kid or not exp_text or not sig:
            self._record("malformed")
            raise VerificationError("«توکن نامعتبر است.»", reason="malformed")
        try:
            exp = int(exp_text)
        except ValueError as exc:  # pragma: no cover - defensive
            self._record("malformed")
            raise VerificationError("«توکن نامعتبر است.»", reason="exp-format") from exc
        envelope = SignatureEnvelope(path="", signed=signed, kid=kid, exp=exp, sig=sig)
        return self.verify(envelope)

    def rotate(self, *, kid: str, secret: str) -> None:
        with self._lock:
            self._keyring = self._keyring.rotate(kid=kid, secret=secret)
        self._record("rotated")

    def export_definitions(self) -> tuple[SigningKeyDefinition, ...]:
        with self._lock:
            return self._keyring.as_definitions()

    def _verify(self, envelope: SignatureEnvelope) -> str:
        path = _decode_path(envelope.signed)
        now_ts = int(self._clock.now().timestamp())
        if envelope.exp <= now_ts:
            self._record("expired")
            raise VerificationError("«لینک دانلود منقضی شده است.»", reason="expired")
        for key in self._keyring.verification_keys():
            if key.kid != envelope.kid:
                continue
            canonical = _canonical("GET", path, {}, envelope.exp)
            expected = _sign(key.secret, canonical)
            if hmac.compare_digest(expected, envelope.sig):
                self._record("ok")
                return path
            self._record("forged")
            raise VerificationError("«توکن نامعتبر است.»", reason="signature")
        self._record("unknown_kid")
        raise VerificationError("«کلید امضا ناشناخته است.»", reason="unknown-kid")

    def _record(self, outcome: str) -> None:
        if self._counter is None:
            return
        try:
            self._counter.labels(outcome=outcome).inc()
        except Exception:  # noqa: BLE001 - metrics must never fail
            pass


def keyring_from_definitions(definitions: Sequence[SigningKeyDefinition]) -> KeyRing:
    keys = [
        SigningKey(definition.kid, definition.secret, "active" if definition.state == "active" else "retired")
        for definition in definitions
    ]
    return KeyRing(tuple(keys))


def _normalize_kid(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        raise KeyRotationError("«شناسه کلید معتبر نیست.»", reason="kid-empty")
    return text


def _normalize_secret(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if len(text) < 32:
        raise KeyRotationError("«راز کلید بسیار کوتاه است.»", reason="secret-short")
    return text


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if normalized.startswith("../") or "/../" in normalized:
        raise VerificationError("«توکن نامعتبر است.»", reason="path-traversal")
    return normalized


def _canonical(method: str, path: str, query: Mapping[str, str], exp: int) -> bytes:
    query_text = "&".join(f"{key}={value}" for key, value in sorted(query.items()))
    payload = f"{method.upper()}\n{path}\n{query_text}\n{exp}"
    return payload.encode("utf-8")


def _encode_path(path: str) -> str:
    return base64.urlsafe_b64encode(path.encode("utf-8")).decode("utf-8").rstrip("=")


def _decode_path(encoded: str) -> str:
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - deterministic Persian error
        raise VerificationError("«توکن نامعتبر است.»", reason="decode") from exc
    return _normalize_path(decoded)


def _sign(secret: str, canonical: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), canonical, "sha256").digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _expiry(now: datetime, ttl_seconds: int) -> int:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return int(now.timestamp()) + max(1, ttl_seconds)


def deterministic_secret(seed: str) -> str:
    """Generate a deterministic secret suitable for rotation tests."""

    digest = sha256(seed.encode("utf-8")).hexdigest()
    # ensure minimum length 48
    return (digest + digest)[0:64]


