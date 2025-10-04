from __future__ import annotations

from pathlib import Path

from tools.guards.wallclock_repo_guard import scan_for_violations


def test_no_baku_literals(clock_test_context) -> None:
    root = Path(__file__).resolve().parents[2]
    targets = [root / "src", root / "tools"]
    violations = scan_for_violations(targets, root=root)
    timezone_violations = [v for v in violations if v.rule == "timezone"]
    debug_context = clock_test_context["get_debug_context"]()
    assert not timezone_violations, (
        "TIMEZONE_FORBIDDEN",
        [f"{violation.path}:{violation.line}" for violation in timezone_violations],
        debug_context,
    )


def test_timezone_allowlist_behavior(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("placeholder", encoding="utf-8")
    runtime_dir = tmp_path / "src"
    runtime_dir.mkdir()
    runtime_file = runtime_dir / "module.py"
    runtime_file.write_text('TZ = "Asia/Baku"\n', encoding="utf-8")

    docs_file = tmp_path / "docs" / "sample.py"
    docs_file.parent.mkdir(parents=True)
    docs_file.write_text('EXAMPLE_TZ = "Asia/Baku"\n', encoding="utf-8")

    guard_file = tmp_path / "tools" / "guards" / "constants.py"
    guard_file.parent.mkdir(parents=True)
    guard_file.write_text('BANNED_TZ = "Asia/Baku"\n', encoding="utf-8")

    violations = scan_for_violations([tmp_path], root=tmp_path)
    runtime_hits = [v for v in violations if v.path == runtime_file and v.rule == "timezone"]
    assert runtime_hits, violations

    allowed_hits = [v for v in violations if v.rule == "timezone" and v.path != runtime_file]
    assert not allowed_hits, allowed_hits
