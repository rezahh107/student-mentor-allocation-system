from __future__ import annotations

from pathlib import Path

FORBIDDEN = ("datetime.now(", "time.time(", "datetime.utcnow(")


def test_no_direct_wall_clock_calls() -> None:
    offenders = []
    for path in Path("repo_auditor_lite").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            if needle in content:
                offenders.append((path, needle))
    assert not offenders, f"Disallowed wall-clock usage detected: {offenders}"
