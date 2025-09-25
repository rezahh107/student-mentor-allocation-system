from __future__ import annotations

import re
from pathlib import Path


def test_no_runtime_asserts() -> None:
    project_root = Path(__file__).resolve().parents[2]
    runtime_dirs = [project_root / "src", project_root / "scripts"]

    violations: list[str] = []
    pattern = re.compile(r"assert(\s|\()")
    for directory in runtime_dirs:
        for path in directory.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            content = path.read_text(encoding="utf-8")
            if pattern.search(content):
                violations.append(str(path.relative_to(project_root)))

    assert not violations, f"assert statements باقی‌مانده در فایل‌ها: {violations}"
