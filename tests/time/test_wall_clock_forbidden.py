"""Ensure phase6 ImportToSabt code never touches wall-clock APIs directly."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "src" / "phase6_import_to_sabt"
ALLOWLIST = {
    SERVICE_ROOT / "app" / "clock.py",
    SERVICE_ROOT / "clock.py",
}
TARGET_FILES = tuple(sorted(p for p in SERVICE_ROOT.rglob("*.py") if p not in ALLOWLIST))


@pytest.mark.parametrize("path", TARGET_FILES)
def test_forbidden_wall_clock_calls_in_src(path: Path) -> None:

    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                target = (func.value.id, func.attr)
                if target in {("datetime", "now"), ("datetime", "utcnow")}:
                    banned.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id == "time" and func.attr == "time":
                    banned.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "time" and node.attr == "time":
                if isinstance(getattr(node, "ctx", None), ast.Load):
                    banned.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert not banned, (
        "TIME_SOURCE_FORBIDDEN: «استفادهٔ مستقیم از زمان سیستم مجاز نیست؛ از Clock تزریق‌شده استفاده کنید.» "
        + ", ".join(banned)
    )

