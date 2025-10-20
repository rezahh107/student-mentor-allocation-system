"""Provider interfaces for manager centers and special schools."""
from __future__ import annotations

from typing import FrozenSet, Protocol


class ManagerCentersProvider(Protocol):
    """Provides allowed centers for a manager."""

    def get_allowed_centers(self, manager_id: int) -> FrozenSet[int] | None:
        """Return allowed centers for the manager or ``None`` when unknown."""


class SpecialSchoolsProvider(Protocol):
    """Provides special school codes per academic year."""

    def get(self, year: int) -> FrozenSet[int] | None:
        """Return special school codes for the year or ``None`` when missing."""

