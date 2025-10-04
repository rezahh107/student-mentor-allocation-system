from __future__ import annotations

from pathlib import Path

from tools.guards.wallclock_repo_guard import scan_for_violations


def test_runtime_forbids_wallclock(clock_test_context) -> None:
    root = Path(__file__).resolve().parents[2]
    targets = [root / "src", root / "tools"]
    violations = scan_for_violations(targets, root=root)
    wallclock = [v for v in violations if v.rule == "wallclock"]
    debug_context = clock_test_context["get_debug_context"]()
    assert not wallclock, (
        "TIME_SOURCE_FORBIDDEN",
        [f"{violation.path}:{violation.line}" for violation in wallclock],
        debug_context,
    )

    clock_test_context["cleanup_log"].append("wallclock-scan")
