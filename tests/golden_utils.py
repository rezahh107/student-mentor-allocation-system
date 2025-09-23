# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


GOLDEN_DIR = Path(__file__).parent / "golden"


def read_golden(name: str) -> str:
    p = GOLDEN_DIR / name
    return p.read_text(encoding="utf-8")


def write_golden(name: str, content: str) -> None:
    p = GOLDEN_DIR / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

