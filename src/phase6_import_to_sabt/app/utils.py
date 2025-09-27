from __future__ import annotations

import os
import unicodedata
from typing import Any, Iterable, Mapping, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from fastapi import FastAPI

ARABIC_DIGITS = {ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")}
PERSIAN_DIGITS = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
ZERO_WIDTH = {
    "\u200c",
    "\u200d",
    "\ufeff",
    "\u2060",
}


def normalize_token(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value
    for zw in ZERO_WIDTH:
        cleaned = cleaned.replace(zw, "")
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = cleaned.translate(ARABIC_DIGITS)
    cleaned = cleaned.translate(PERSIAN_DIGITS)
    return cleaned.strip()


def ensure_no_control_chars(items: Iterable[str]) -> None:
    for item in items:
        for ch in item:
            if unicodedata.category(ch)[0] == "C" and ch not in ZERO_WIDTH:
                raise ValueError("Control characters not permitted in headers")


def get_debug_context(
    app: "FastAPI" | None = None,
    *,
    redis_keys: Sequence[str] | None = None,
    namespace: str | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic debug context without leaking secrets."""

    context: dict[str, Any] = {"env": os.getenv("GITHUB_ACTIONS", "local")}
    if namespace:
        context["namespace"] = namespace
    if redis_keys is not None:
        context["redis_keys"] = list(redis_keys)
    if last_error is not None:
        context["last_error"] = last_error
    if app is not None:
        diagnostics = getattr(app.state, "diagnostics", None)
        if isinstance(diagnostics, Mapping):
            context["middleware_chain"] = diagnostics.get("last_chain", [])
            context["rate_limit_state"] = diagnostics.get("last_rate_limit")
            context["idempotency_state"] = diagnostics.get("last_idempotency")
            context["auth_state"] = diagnostics.get("last_auth")
    return context


__all__ = ["normalize_token", "ensure_no_control_chars", "get_debug_context"]
