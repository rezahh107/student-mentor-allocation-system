"""Shared regular expression patterns and normalization helpers."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Pattern

__all__ = [
    "ascii_token_pattern",
    "zero_width_pattern",
    "formula_prefixes",
]

_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@")


@lru_cache(maxsize=None)
def ascii_token_pattern(max_length: int = 128) -> Pattern[str]:
    """Return the compiled pattern for ASCII credential tokens."""

    max_length = max(16, int(max_length))
    return re.compile(rf"^[A-Za-z0-9._-]{{16,{max_length}}}$")


@lru_cache(maxsize=1)
def zero_width_pattern() -> Pattern[str]:
    """Return a compiled pattern matching zero-width / bidi characters."""

    return re.compile("[\u200B\u200C\u200D\u200E\u200F]")


def formula_prefixes() -> tuple[str, ...]:
    """Expose the tuple of Excel formula-leading prefixes."""

    return _FORMULA_PREFIXES
