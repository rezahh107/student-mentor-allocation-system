"""Helpers for normalizing environment variables with Persian-safe rules."""

from __future__ import annotations

from typing import Optional

from sma.phase6_import_to_sabt.sanitization import sanitize_text

_EXTRA_DIRECTIONALS = ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c")


def sanitize_env_text(value: Optional[str]) -> str:
    """Return a sanitized string removing zero-width directionals."""

    text = sanitize_text(value or "")
    for marker in _EXTRA_DIRECTIONALS:
        text = text.replace(marker, "")
    return text.strip()


__all__ = ["sanitize_env_text"]
