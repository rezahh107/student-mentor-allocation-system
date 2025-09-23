# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Set

from src.domain.shared.types import Gender


@dataclass(slots=True)
class Mentor:
    mentor_id: int
    name: Optional[str]
    gender: Gender
    type: str  # 'عادی' | 'مدرسه'
    capacity: int = 60
    current_load: int = 0
    alias_code: Optional[str] = None
    manager_id: Optional[int] = None
    is_active: bool = True
    allowed_groups: Set[int] = field(default_factory=set)
    allowed_centers: Set[int] = field(default_factory=set)
    school_codes: Set[int] = field(default_factory=set)

    def has_capacity(self) -> bool:
        return self.current_load < self.capacity

    @property
    def occupancy_ratio(self) -> float:
        if self.capacity <= 0:
            return 1.0
        return self.current_load / float(self.capacity)

