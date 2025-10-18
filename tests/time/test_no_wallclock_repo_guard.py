from __future__ import annotations

from pathlib import Path

import pytest

FORBIDDEN = ["datetime.now", "time.time", "time.sleep"]


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_wall_clock_calls_in_repo(pattern: str) -> None:
    tooling_dir = Path("tooling")
    offenders = []
    for file in tooling_dir.rglob("*.py"):
        if pattern in file.read_text(encoding="utf-8"):
            offenders.append(file)
    assert not offenders, f"Found forbidden pattern {pattern} in {offenders}"
