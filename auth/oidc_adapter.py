from __future__ import annotations

import asyncio
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping

import httpx

from sma.reliability.clock import Clock

if TYPE_CHECKING:
    from sma.debug.debug_context import DebugContext

from .errors import AuthError, ProviderError
from .metrics import AuthMetrics
from .models import BridgeSession
from .session_store import SessionStore
from .utils import (
    encode_base64url,
    exponential_backoff,
    hash_identifier,
    log_event,
    masked,
    merge_claims,
    parse_jwt,
    sanitize_scope,
)

LOGGER = logging.getLogger("sso.oidc")


@dataclass(slots=True)
class OIDCSettings:
    client_id: str
    client_secret: str
    issuer: str
    token_endpoint: str
    jwks_endpoint: str
    auth_endpoint: str
    scopes: tuple[str, ...]


class JWKSCache:
    def __init__(self, *, ttl_seconds: int, clock: Clock) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._expires_at: datetime | None = None
        self._keys: dict[str, Mapping[str, Any]] | None = None

    def get(self) -> dict[str, Mapping[str, Any]] | None:
        if self._keys is None:
            return None
        if self._expires_at is None:
            return None
        if self._clock.now() >= self._expires_at:
            return None
        return self._keys

    def set(self, keys: dict[str, Mapping[str, Any]]) -> None:
        self._keys = keys
        self._expires_at = self._clock.now() + timedelta(seconds=self._ttl_seconds)


class OIDCAdapter:
    def __init__(
        self,
        settings: OIDCSettings,
        *,
        http_client: httpx.AsyncClient,
        session_store: SessionStore,
        metrics: AuthMetrics,
        clock: Clock,
        audit_sink: Callable[[str, str, Mapping[str, Any]], Awaitable[None]],
        ldap_mapper: Callable[[Mapping[str, Any]], Awaitable[tuple[str, str]]] | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 0.1,
        jwks_ttl_seconds: int = 300,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client
        self._session_store = session_store
        self._metrics = metrics
        self._clock = clock
        self._audit_sink = audit_sink
        self._ldap_mapper = ldap_mapper
        self._max_retries = max(1, max_retries)
        self._backoff_seconds = backoff_seconds
        self._jwks_cache = JWKSCache(ttl_seconds=jwks_ttl_seconds, clock=clock)
        self._sleep = sleep or asyncio.sleep

    async def authorization_url(self, *, state: str, nonce: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._settings.client_id,
            "redirect_uri": f"{self._settings.issuer}/callback",
            "scope": " ".join(self._settings.scopes),
            "state": state,
            "nonce": nonce,
        }
        query = httpx.QueryParams(params)
        return f"{self._settings.auth_endpoint}?{query}"

    async def authenticate(
        self,
        *,
        code: str,
        correlation_id: str,
        request_id: str,
        debug: "DebugContext | None" = None,
    ) -> BridgeSession:
        histogram = self._metrics.duration_seconds.labels(provider="oidc")
        with histogram.time():
            try:
                token_payload = await self._exchange(code, correlation_id, debug)
                claims = await self._validate_id_token(token_payload["id_token"], correlation_id, debug)
                claims = merge_claims(claims, token_payload.get("userinfo"))
                role, scope = await self._map_attributes(claims, correlation_id)
                subject = str(claims.get("sub") or claims.get("subject") or "anonymous")
                session = await self._session_store.create(
                    correlation_id=correlation_id,
                    subject=subject,
                    role=role,
                    center_scope=scope,
                )
                await self._audit("AUTHN_OK", correlation_id, request_id, role=role, scope=scope)
                self._metrics.ok_total.labels(provider="oidc").inc()
                log_event(
                    LOGGER,
                    msg="OIDC_AUTH_OK",
                    rid=request_id,
                    cid=masked(correlation_id),
                    role=role,
                    scope=scope,
                )
                return session
            except AuthError as exc:
                self._metrics.fail_total.labels(provider="oidc", reason=exc.reason).inc()
                await self._audit("AUTHN_FAIL", correlation_id, request_id, error=exc.reason)
                if debug:
                    debug.set_last_error(code=exc.code, message=exc.message_fa)
                log_event(
                    LOGGER,
                    msg="OIDC_AUTH_FAIL",
                    rid=request_id,
                    cid=masked(correlation_id),
                    error=exc.reason,
                )
                raise

    async def _exchange(
        self,
        code: str,
        correlation_id: str,
        debug: "DebugContext | None",
    ) -> Mapping[str, Any]:
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret,
            "redirect_uri": f"{self._settings.issuer}/callback",
        }
        last_error: Exception | None = None
        reason = "token"
        for attempt in range(1, self._max_retries + 1):
            started = self._clock.now()
            response: httpx.Response | None = None
            try:
                response = await self._http.post(self._settings.token_endpoint, data=body, timeout=5.0)
                response.raise_for_status()
                self._record_http_attempt(
                    method="POST",
                    url=self._settings.token_endpoint,
                    status=response.status_code,
                    started=started,
                    debug=debug,
                )
                return response.json()
            except Exception as exc:  # noqa: BLE001 - network errors collapsed
                last_error = exc
                status = response.status_code if response is not None else None
                self._record_http_attempt(
                    method="POST",
                    url=self._settings.token_endpoint,
                    status=status,
                    started=started,
                    debug=debug,
                )
                if attempt == self._max_retries:
                    self._metrics.retry_exhaustion_total.labels(adapter="oidc", reason=reason).inc()
                    break
                self._metrics.retry_attempts_total.labels(adapter="oidc", reason=reason).inc()
                delay = exponential_backoff(
                    self._backoff_seconds,
                    attempt,
                    jitter_seed=f"{correlation_id}:{reason}",
                )
                self._metrics.retry_backoff_seconds.labels(adapter="oidc", reason=reason).observe(delay)
                await self._sleep(delay)
        message = "خطا در ارتباط با ارائه‌دهندهٔ هویت؛ بعداً تلاش کنید."
        if debug:
            debug.set_last_error(code="AUTH_IDP_ERROR", message=message)
        raise ProviderError(
            code="AUTH_IDP_ERROR",
            message_fa=message,
            reason="token_exchange_failed",
        ) from last_error

    async def _validate_id_token(
        self,
        token: str,
        correlation_id: str,
        debug: "DebugContext | None",
    ) -> Mapping[str, Any]:
        header, payload, signature = parse_jwt(token)
        kid = header.get("kid")
        if not kid:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="توکن بازگشتی نامعتبر است.",
                reason="missing_kid",
            )
        key_data = await self._resolve_jwks_key(str(kid), correlation_id, debug)
        self._verify_signature(header, payload, signature, key_data)
        self._validate_claims(payload)
        return payload

    def _verify_signature(
        self,
        header: Mapping[str, Any],
        payload: Mapping[str, Any],
        signature: bytes,
        key_data: Mapping[str, Any],
    ) -> None:
        alg = header.get("alg")
        if alg != "HS256":
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="الگوریتم پشتیبانی نمی‌شود.",
                reason="unsupported_alg",
            )
        secret = key_data.get("k")
        if not isinstance(secret, str):
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="کلید نامعتبر است.",
                reason="invalid_key",
            )
        signing_input = f"{encode_base64url(json.dumps(header).encode())}.{encode_base64url(json.dumps(payload).encode())}".encode()
        digest = hmac.new(secret.encode("utf-8"), signing_input, digestmod="sha256").digest()
        if not hmac.compare_digest(digest, signature):
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="توکن بازگشتی نامعتبر است.",
                reason="bad_signature",
            )

    def _validate_claims(self, payload: Mapping[str, Any]) -> None:
        issuer = payload.get("iss")
        if issuer != self._settings.issuer:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="صادرکنندهٔ نامعتبر.",
                reason="invalid_issuer",
            )
        audience = payload.get("aud")
        if isinstance(audience, str):
            audiences = {audience}
        elif isinstance(audience, (list, tuple, set)):
            audiences = {str(item) for item in audience}
        else:
            audiences = set()
        if self._settings.client_id not in audiences:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="شناسهٔ مشتری تطابق ندارد.",
                reason="invalid_audience",
            )
        now = self._clock.now().timestamp()
        exp = float(payload.get("exp", 0))
        nbf = float(payload.get("nbf", 0))
        if now >= exp:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="توکن منقضی شده است.",
                reason="expired",
            )
        if now < nbf:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="توکن هنوز فعال نشده است.",
                reason="not_active",
            )

    async def _refresh_jwks(
        self,
        correlation_id: str,
        debug: "DebugContext | None",
    ) -> dict[str, Mapping[str, Any]]:
        started = self._clock.now()
        response: httpx.Response | None = None
        try:
            response = await self._http.get(self._settings.jwks_endpoint, timeout=5.0)
            response.raise_for_status()
            payload = response.json()
            self._record_http_attempt(
                method="GET",
                url=self._settings.jwks_endpoint,
                status=response.status_code,
                started=started,
                debug=debug,
            )
        except Exception:
            status = response.status_code if response is not None else None
            self._record_http_attempt(
                method="GET",
                url=self._settings.jwks_endpoint,
                status=status,
                started=started,
                debug=debug,
            )
            raise
        keys = {item["kid"]: item for item in payload.get("keys", []) if "kid" in item}
        self._jwks_cache.set(keys)
        log_event(
            LOGGER,
            msg="OIDC_JWKS_REFRESHED",
            cid=masked(correlation_id),
            keys=list(keys),
        )
        return keys

    async def _resolve_jwks_key(
        self,
        kid: str,
        correlation_id: str,
        debug: "DebugContext | None",
    ) -> Mapping[str, Any]:
        cached = self._jwks_cache.get() or {}
        if kid in cached:
            return cached[kid]
        reason = "jwks"
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                keys = await self._refresh_jwks(correlation_id, debug)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                keys = {}
            cached_key = keys.get(kid)
            if cached_key:
                return cached_key
            if attempt == self._max_retries:
                self._metrics.retry_exhaustion_total.labels(adapter="oidc", reason=reason).inc()
                message = "کلیدهای امضای ورود نامعتبر/به‌روز نشده‌اند؛ لطفاً بعداً تلاش کنید."
                if debug:
                    debug.set_last_error(code="AUTH_JWKS_EXHAUSTED", message=message)
                raise ProviderError(
                    code="AUTH_JWKS_EXHAUSTED",
                    message_fa=message,
                    reason="jwks",
                ) from last_error
            self._metrics.retry_attempts_total.labels(adapter="oidc", reason=reason).inc()
            delay = exponential_backoff(
                self._backoff_seconds,
                attempt,
                jitter_seed=f"{correlation_id}:{reason}",
            )
            self._metrics.retry_backoff_seconds.labels(adapter="oidc", reason=reason).observe(delay)
            await self._sleep(delay)
        # Defensive: should never reach here due to raise above
        raise ProviderError(
            code="AUTH_IDP_ERROR",
            message_fa="کلید امضای توکن یافت نشد.",
            reason="unknown_kid",
        )

    def _record_http_attempt(
        self,
        *,
        method: str,
        url: str,
        status: int | None,
        started: datetime,
        debug: "DebugContext | None",
    ) -> None:
        if not debug:
            return
        duration = max(0.0, (self._clock.now() - started).total_seconds())
        debug.record_http_attempt(
            method=method,
            url=url,
            status=status,
            duration=duration,
        )

    async def _map_attributes(self, claims: Mapping[str, Any], correlation_id: str) -> tuple[str, str]:
        role_raw = str(claims.get("role") or "").strip().upper()
        scope_raw = claims.get("center_scope")
        if self._ldap_mapper:
            role_raw, scope_raw = await self._ldap_mapper(claims, correlation_id=correlation_id)
        if role_raw not in {"ADMIN", "MANAGER"}:
            raise ProviderError(
                code="AUTH_FORBIDDEN",
                message_fa="دسترسی مجاز نیست؛ نقش یا اسکوپ کافی نیست.",
                reason="invalid_role",
            )
        try:
            scope = "ALL" if role_raw == "ADMIN" else sanitize_scope(str(scope_raw) if scope_raw is not None else "")
        except ValueError as exc:  # noqa: BLE001
            raise ProviderError(
                code="AUTH_FORBIDDEN",
                message_fa="دسترسی مجاز نیست؛ نقش یا اسکوپ کافی نیست.",
                reason="invalid_scope",
            ) from exc
        return role_raw, scope

    async def _audit(self, action: str, correlation_id: str, request_id: str, **fields: Any) -> None:
        payload = {
            "action": action,
            "cid": hash_identifier(correlation_id),
            "request_id": request_id,
            **fields,
            "ts": self._clock.now().isoformat(),
        }
        await self._audit_sink(action, correlation_id, payload)


__all__ = ["OIDCAdapter", "OIDCSettings"]
