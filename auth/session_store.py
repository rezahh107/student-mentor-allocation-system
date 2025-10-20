from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Protocol

from sma.reliability.clock import Clock

from .errors import ProviderError
from .models import BridgeSession
from .utils import build_sid, log_event

LOGGER = logging.getLogger("sso.session")


class SessionSerializer(Protocol):
    def dumps(self, session: BridgeSession) -> str: ...

    def loads(self, payload: str) -> BridgeSession: ...


class JSONSessionSerializer:
    def dumps(self, session: BridgeSession) -> str:
        payload = asdict(session)
        payload["issued_at"] = session.issued_at.isoformat()
        payload["expires_at"] = session.expires_at.isoformat()
        return json.dumps(payload)

    def loads(self, payload: str) -> BridgeSession:
        data = json.loads(payload)
        return BridgeSession(
            sid=data["sid"],
            role=data["role"],
            center_scope=data["center_scope"],
            issued_at=datetime.fromisoformat(data["issued_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )


class SessionStore:
    """Redis-backed bridge session repository."""

    def __init__(
        self,
        redis: Any,
        *,
        ttl_seconds: int,
        clock: Clock,
        namespace: str = "sso_session",
        serializer: SessionSerializer | None = None,
    ) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._namespace = namespace
        self._serializer = serializer or JSONSessionSerializer()

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def _key(self, sid: str) -> str:
        return f"{self._namespace}:{sid}"

    async def create(
        self,
        *,
        correlation_id: str,
        subject: str,
        role: str,
        center_scope: str,
    ) -> BridgeSession:
        sid = build_sid(correlation_id, subject, clock=self._clock)
        issued_at = self._clock.now()
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)
        session = BridgeSession(
            sid=sid,
            role=role,  # type: ignore[arg-type]
            center_scope=center_scope,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        payload = self._serializer.dumps(session)
        key = self._key(sid)
        result = self._redis.set(key, payload, ex=self._ttl_seconds, nx=True)
        ok = await result if hasattr(result, "__await__") else result
        if not ok:
            log_event(LOGGER, msg="SSO_SESSION_COLLISION", sid=sid)
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="خطا در ایجاد نشست؛ بعداً تلاش کنید.",
                reason="session_collision",
            )
        log_event(
            LOGGER,
            msg="SSO_SESSION_CREATED",
            sid=sid,
            ttl=self._ttl_seconds,
        )
        return session

    async def get(self, sid: str) -> BridgeSession | None:
        result = self._redis.get(self._key(sid))
        payload = await result if hasattr(result, "__await__") else result
        if payload is None:
            return None
        data = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else payload
        session = self._serializer.loads(data)
        return session

    async def delete(self, sid: str) -> None:
        result = self._redis.delete(self._key(sid))
        if hasattr(result, "__await__"):
            await result


__all__ = ["SessionStore", "JSONSessionSerializer"]
