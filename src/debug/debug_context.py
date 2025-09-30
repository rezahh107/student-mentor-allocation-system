from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.app.context import set_debug_context


_ALLOWED_PREFIXES = ("sso_session:", "idem:", "ratelimit:")
_PII_PATTERN = re.compile(r"email|phone|national_id", re.IGNORECASE)


def _hash_text(value: str) -> str:
    digest = blake2b(digest_size=16)
    digest.update(value.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


@dataclass(slots=True)
class DebugContext:
    """Collect deterministic debug information for assertions and logs."""

    rid: str
    operation: str
    namespace: str
    redis_scan: Callable[[str], Iterable[str]] | None = None
    audit_events: Callable[[], Sequence[Mapping[str, Any]]] | None = None
    http_attempts: list[Mapping[str, Any]] = field(default_factory=list)
    last_error: Mapping[str, Any] | None = None

    def record_http_attempt(
        self,
        *,
        method: str,
        url: str,
        status: int | None,
        duration: float,
    ) -> None:
        attempt = {
            "method": method.upper(),
            "url": url,
            "status": status if status is not None else -1,
            "duration": round(duration, 6),
        }
        self.http_attempts.append(attempt)

    def set_last_error(self, *, code: str, message: str | None = None) -> None:
        masked_message = _hash_text(message) if message else None
        self.last_error = {"code": code, "message": masked_message}

    def snapshot(self) -> dict[str, Any]:
        data = {
            "rid": self.rid,
            "operation": self.operation,
            "namespace": self.namespace,
            "redis_keys": self._collect_redis_keys(),
            "audit_events": self._collect_audit_events(),
            "http_attempts": list(self.http_attempts),
            "last_error": self.last_error,
        }
        self._ensure_no_pii(data)
        return data

    def to_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False, sort_keys=True)

    def as_json(self) -> str:
        """Alias used by logging enrichers expecting explicit naming."""

        return self.to_json()

    def _collect_redis_keys(self) -> list[str]:
        if not self.redis_scan:
            return []
        collected: set[str] = set()
        for prefix in _ALLOWED_PREFIXES:
            pattern = f"{prefix}*"
            for key in self.redis_scan(pattern):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", errors="ignore")
                if not isinstance(key, str):
                    continue
                if any(key.startswith(p) for p in _ALLOWED_PREFIXES):
                    collected.add(key)
        return sorted(collected)

    def _collect_audit_events(self) -> list[dict[str, Any]]:
        if not self.audit_events:
            return []
        events = list(self.audit_events())[-5:]
        sanitized: list[dict[str, Any]] = []
        for event in events:
            action = event.get("action")
            cid = event.get("cid")
            correlation = event.get("correlation_id")
            sanitized.append(
                {
                    "action": action,
                    "cid": cid or (_hash_text(str(correlation)) if correlation else None),
                    "ts": event.get("ts"),
                }
            )
        return sanitized

    def _ensure_no_pii(self, payload: Mapping[str, Any]) -> None:
        dump = json.dumps(payload, ensure_ascii=False)
        if _PII_PATTERN.search(dump):
            raise ValueError("PII detected in debug context")


@dataclass(slots=True)
class DebugContextFactory:
    """Factory that binds :class:`DebugContext` to the logging context."""

    redis: Any | None = None
    audit_fetcher: Callable[[], Sequence[Mapping[str, Any]]] | None = None
    namespace: str | None = None

    def __call__(
        self,
        request: Any | None = None,
        *,
        rid: str | None = None,
        operation: str | None = None,
        namespace: str | None = None,
    ) -> DebugContext:
        resolved_rid = rid or self._resolve_rid(request)
        resolved_operation = operation or self._resolve_operation(request)
        resolved_namespace = namespace or self._resolve_namespace(request)
        ctx = DebugContext(
            rid=resolved_rid,
            operation=resolved_operation,
            namespace=resolved_namespace,
            redis_scan=self._build_redis_scanner(),
            audit_events=self._build_audit_fetcher(),
        )
        token = set_debug_context(ctx)
        if request is not None and hasattr(request, "state"):
            setattr(request.state, "debug_ctx", ctx)
            setattr(request.state, "debug_ctx_token", token)
        return ctx

    def _build_redis_scanner(self) -> Callable[[str], Iterable[str]] | None:
        client = self.redis
        if client is None:
            return None

        def scanner(pattern: str) -> Iterable[str]:
            try:
                iterator = getattr(client, "scan_iter", None)
                if iterator is None:
                    return []
                result = iterator(match=pattern)
                if hasattr(result, "__await__"):
                    return []
                if hasattr(result, "__aiter__"):
                    return []
                return list(result)
            except Exception:
                return []

        return scanner

    def _build_audit_fetcher(self) -> Callable[[], Sequence[Mapping[str, Any]]] | None:
        if self.audit_fetcher is None:
            return None

        def loader() -> Sequence[Mapping[str, Any]]:
            try:
                events = list(self.audit_fetcher())
            except Exception:
                return []
            sanitized: list[dict[str, Any]] = []
            for event in events:
                sanitized.append(
                    {
                        "id": event.get("id"),
                        "action": event.get("action"),
                        "correlation_id": event.get("correlation_id"),
                        "ts": event.get("ts"),
                    }
                )
            return sanitized

        return loader

    def _resolve_rid(self, request: Any | None) -> str:
        if request is None:
            return "anonymous"
        headers = getattr(request, "headers", None)
        if headers:
            value = headers.get("X-Request-ID") if hasattr(headers, "get") else None
            if value:
                stripped = value.strip()
                if stripped:
                    return stripped
        state = getattr(request, "state", None)
        if state is not None and getattr(state, "rid", None):
            return getattr(state, "rid")
        return "anonymous"

    def _resolve_operation(self, request: Any | None) -> str:
        if request is None:
            return "unknown"
        scope = getattr(request, "scope", {}) or {}
        endpoint = scope.get("endpoint") if isinstance(scope, dict) else None
        if endpoint is not None:
            name = getattr(endpoint, "__name__", None)
            if name:
                return name
        path = scope.get("path") if isinstance(scope, dict) else None
        if path:
            return str(path)
        url = getattr(request, "url", None)
        if url:
            return str(url)
        method = getattr(request, "method", None)
        if method:
            return str(method)
        return "unknown"

    def _resolve_namespace(self, request: Any | None) -> str:
        if namespace := self.namespace:
            return namespace
        if request is None:
            return "debug"
        scope = getattr(request, "scope", {}) or {}
        endpoint = scope.get("endpoint") if isinstance(scope, dict) else None
        if endpoint is not None:
            module = getattr(endpoint, "__module__", None)
            if module:
                return module
        app = getattr(request, "app", None)
        if app is not None:
            title = getattr(app, "title", None)
            if title:
                return str(title)
        return "debug"


def default_debug_context_factory(
    *,
    redis: Any | None,
    audit_fetcher: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
    namespace: str | None = None,
) -> DebugContextFactory:
    """Convenience helper for configuring the default factory."""

    return DebugContextFactory(redis=redis, audit_fetcher=audit_fetcher, namespace=namespace)


__all__ = [
    "DebugContext",
    "DebugContextFactory",
    "default_debug_context_factory",
]
