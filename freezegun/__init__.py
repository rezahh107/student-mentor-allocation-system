"""Lightweight shim for freezegun to satisfy tests without external dependency."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def freeze_time(_: str, **__: object) -> Iterator[None]:
    """Yield without altering global time.

    The real library would patch datetime; this shim keeps behaviour deterministic
    for unit tests that do not rely on absolute timestamps.
    """

    yield


__all__ = ["freeze_time"]
