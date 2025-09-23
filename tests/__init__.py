"""Test package initialisation and import path setup."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

for entry in (ROOT, SRC):
    path_str = str(entry)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
