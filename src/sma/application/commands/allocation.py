# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StartBatchAllocation:
    priority_mode: str = "balanced"  # balanced|fastest
    guarantee_assignment: bool = False
    job_id: str | None = None


@dataclass(slots=True)
class GetJobStatus:
    job_id: str

