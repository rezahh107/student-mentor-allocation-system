"""Minimal multipart parser stub for test environments."""

from __future__ import annotations

from typing import Tuple


def parse_options_header(value: str) -> Tuple[str, dict[str, str]]:
    """Return value and empty options to satisfy FastAPI checks."""

    return value, {}


__all__ = ["parse_options_header"]
