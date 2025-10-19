from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, List, Optional


@dataclasses.dataclass
class RequirementLine:
    raw: str
    name: Optional[str]
    spec: str = ""
    marker: str = ""
    extras: str = ""
    is_include: bool = False
    include_target: Optional[str] = None

    @property
    def normalized_name(self) -> Optional[str]:
        return self.name.lower() if self.name else None


@dataclasses.dataclass
class RequirementFile:
    path: Path
    lines: List[RequirementLine]
    original_text: str
    newline: str


@dataclasses.dataclass
class PlanAction:
    file: Path
    updated_text: str
    reasons: List[str]


@dataclasses.dataclass
class PlanResult:
    plan_id: str
    policy: str
    actions: Dict[Path, PlanAction]
    diff: str
    messages: List[str]
