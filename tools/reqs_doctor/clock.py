
from __future__ import annotations

from datetime import datetime, timedelta

FIXED_TIMESTAMP = "2024-01-01T00:00:00+03:30"


class DeterministicClock:
    """Minimal deterministic clock with freeze/tick semantics for tests."""

    def __init__(self, fixed_iso: str = FIXED_TIMESTAMP) -> None:
        self._instant = datetime.fromisoformat(fixed_iso)

    def now(self) -> datetime:
        return self._instant

    def iso(self) -> str:
        return self._instant.isoformat()

    def tick(self, *, seconds: float) -> None:
        self._instant += timedelta(seconds=max(0.0, float(seconds)))

    def freeze(self, iso_text: str | None) -> None:
        if iso_text:
            self._instant = datetime.fromisoformat(iso_text)


def tehran_clock() -> DeterministicClock:
    return DeterministicClock()
