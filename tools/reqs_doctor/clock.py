
from __future__ import annotations
FIXED_TIMESTAMP = "2024-01-01T00:00:00+03:30"
class DeterministicClock:
    def __init__(self, fixed_iso: str = FIXED_TIMESTAMP) -> None:
        self._iso = fixed_iso
    def iso(self) -> str:
        return self._iso
def tehran_clock() -> DeterministicClock:
    return DeterministicClock()
