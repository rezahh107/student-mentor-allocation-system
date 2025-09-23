# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PerfReport:
    students: int
    elapsed_sec: float
    qps: float


def write_report(path: str, report: PerfReport) -> None:
    Path(path).write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

