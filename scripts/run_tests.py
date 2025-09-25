from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess  # اجرای کنترل‌شده ابزارهای تست؛ ورودی‌ها محدود هستند. # nosec B404
import sys
from pathlib import Path
from typing import Iterable, Sequence, Set

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.logging_config import setup_logging

setup_logging()
REPORT_PATH = ROOT / "report.json"
BENCHMARK_PATH = ROOT / "benchmark.json"
COVERAGE_PATH = ROOT / "coverage.json"
GATES_PATH = ROOT / "gates.json"
DEFAULT_BENCHMARK_LIMIT_MS = 250.0
THRESHOLD_CONFIG = ROOT / "config" / "performance_thresholds.json"


def format_cmd(cmd: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) if " " in part else part for part in cmd)


def run(cmd: Sequence[str], *, capture: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    printable = format_cmd(cmd)
    print(f"[run_tests] $ {printable}")
    kwargs: dict[str, object] = {"cwd": str(ROOT), "env": env}
    if capture:
        kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True})
    else:
        kwargs.update({"text": True})
    try:
        return subprocess.run(cmd, check=False, **kwargs)  # دستورات تست بدون shell و با کنترل ورودی اجرا می‌شوند. # nosec B603
    except FileNotFoundError as exc:
        name = cmd[0]
        print(f"[run_tests] command not found: {name}: {exc}")
        completed = subprocess.CompletedProcess(cmd, 1)
        if capture:
            completed.stdout = ""
            completed.stderr = str(exc)
        return completed


def tokenize_path(path: Path) -> Set[str]:
    tokens: Set[str] = set()
    for part in path.parts:
        clean = part.replace(".py", "").replace("-", "_")
        for token in clean.split("_"):
            if token and token not in {"src", "tests"}:
                tokens.add(token.lower())
    return tokens


def discover_tests() -> list[Path]:
    tests_root = ROOT / "tests"
    if not tests_root.exists():
        return []
    return [path for path in tests_root.rglob("test_*.py") if path.is_file()]


def match_tests_for_source(source: Path, tests: Sequence[Path]) -> Set[str]:
    if not tests:
        return set()
    rel_source = source.relative_to(ROOT)
    src_tokens = tokenize_path(rel_source)
    related: Set[str] = set()
    for test_path in tests:
        rel = test_path.relative_to(ROOT)
        test_tokens = tokenize_path(rel)
        if src_tokens & test_tokens:
            related.add(rel.as_posix())
    return related


def get_changed_files(base_hint: str | None) -> list[str]:
    candidates: list[str] = []
    if base_hint:
        candidates.append(base_hint)
    candidates.extend(["HEAD~1", "origin/main", "main"])
    seen: Set[str] = set()
    for ref in candidates:
        if ref in seen:
            continue
        seen.add(ref)
        probe = run(["git", "rev-parse", "--verify", ref], capture=True)
        if probe.returncode != 0:
            continue
        diff = run(["git", "diff", "--name-only", f"{ref}...HEAD"], capture=True)
        if diff.returncode == 0 and diff.stdout:
            files = [line.strip().replace("\\", "/") for line in diff.stdout.splitlines() if line.strip()]
            if files:
                return files
    status = run(["git", "status", "--porcelain"], capture=True)
    if status.returncode == 0 and status.stdout:
        rows = []
        for line in status.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("??"):
                continue
            rows.append(line[3:].strip().replace("\\", "/"))
        if rows:
            return rows
    return []


def compute_tests_from_changes(changed: Iterable[str]) -> list[str]:
    discovered = discover_tests()
    selected: Set[str] = set()
    for rel in changed:
        normalized = rel.replace("\\", "/")
        if not normalized.endswith(".py"):
            continue
        if normalized.startswith("tests/"):
            selected.add(normalized)
        elif normalized.startswith("src/"):
            path = ROOT / normalized
            if path.exists():
                selected.update(match_tests_for_source(path, discovered))
    return sorted(selected)


def select_targets(args: argparse.Namespace) -> tuple[list[str], str, list[str]]:
    explicit = [target.replace("\\", "/") for target in (args.paths or [])]
    if explicit:
        return explicit, "explicit paths provided", []
    changed = get_changed_files(args.base)
    if args.scope == "all":
        return [], "full suite requested", changed
    computed = compute_tests_from_changes(changed)
    if args.scope == "tests":
        filtered = [path for path in computed if path.startswith("tests/")]
        if filtered:
            return filtered, "limited to touched tests", changed
        return [], "no test files changed; running full suite", changed
    if args.scope == "changed":
        if computed:
            return computed, "running tests mapped from changed files", changed
        return [], "no mapped tests; running entire suite", changed
    if computed:
        return computed, "auto-selected tests mapped from recent changes", changed
    if changed:
        return [], "changes detected but no mapped tests; running full suite", changed
    return [], "no git diff detected; running full suite", changed


def ensure_artifact(path: Path, payload: object) -> None:
    if path.exists():
        return
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[run_tests] wrote fallback artifact: {path.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"[run_tests] failed to create fallback artifact {path}: {exc}")


def load_threshold_overrides() -> dict[str, float]:
    if THRESHOLD_CONFIG.exists():
        try:
            data = json.loads(THRESHOLD_CONFIG.read_text(encoding="utf-8"))
            return {str(k): float(v) for k, v in data.items()}
        except Exception as exc:  # noqa: BLE001
            print(f"[run_tests] failed to read threshold config {THRESHOLD_CONFIG}: {exc}")
    return {}


def enforce_performance_gate(threshold_override: float | None, disable: bool) -> tuple[bool, float, list[str]]:
    if disable:
        return True, threshold_override or DEFAULT_BENCHMARK_LIMIT_MS, []
    overrides = load_threshold_overrides()
    threshold_ms = threshold_override if threshold_override is not None else float(os.getenv("PERF_MAX_MEAN_MS", DEFAULT_BENCHMARK_LIMIT_MS))
    try:
        bench_data = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return True, threshold_ms, []
    benchmarks = bench_data.get("benchmarks") or []
    breaches: list[str] = []
    for entry in benchmarks:
        name = str(entry.get("name") or entry.get("fullname") or "benchmark")
        stats = entry.get("stats") or {}
        mean = stats.get("mean")
        if mean is None:
            continue
        limit = overrides.get(name, threshold_ms)
        mean_ms = float(mean) * 1000.0
        if mean_ms > limit:
            breaches.append(f"{name}: mean {mean_ms:.2f} ms > {limit:.2f} ms")
    return (len(breaches) == 0), threshold_ms, breaches


def clear_previous_artifacts() -> None:
    for path in (REPORT_PATH, BENCHMARK_PATH, COVERAGE_PATH):
        if path.exists():
            try:
                path.unlink()
            except Exception as exc:  # noqa: BLE001
                print(f"[run_tests] warning: failed to remove {path}: {exc}")


def prepare_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def run_watch_mode(pytest_args: list[str], targets: list[str], env: dict[str, str]) -> int:
    watch_cmd = [sys.executable, "-m", "pytest", *pytest_args, *targets]
    runner = format_cmd(watch_cmd)
    proc = run(["ptw", "--runner", runner], env=env)
    return proc.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Continuous testing helper with selective execution and gates.")
    parser.add_argument("--scope", choices=["auto", "all", "changed", "tests"], default="auto", help="Execution scope. auto=smart selection based on git diff.")
    parser.add_argument("--base", help="Git ref to diff against when computing changed files.")
    parser.add_argument("--paths", nargs="*", help="Explicit test paths or node ids to run.")
    parser.add_argument("--marker", action="append", dest="markers", help="Limit run to pytest marker(s).")
    parser.add_argument("--parallel", action="store_true", help="Run tests in parallel via pytest-xdist.")
    parser.add_argument("--workers", help="Worker count for --parallel (default: auto).")
    parser.add_argument("--perf-threshold", type=float, help="Performance threshold in milliseconds for benchmark means.")
    parser.add_argument("--no-perf-gate", action="store_true", help="Disable performance gating failures.")
    parser.add_argument("--watch", action="store_true", help="Run in watch mode using pytest-watch (ptw).")
    parser.add_argument("--dry-run", action="store_true", help="Print selection info without running tests.")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="Arguments passed through to pytest (prefix with --).")
    args = parser.parse_args(argv)

    targets, reason, changed = select_targets(args)
    print(f"[run_tests] scope={args.scope} | reason={reason}")
    if changed:
        print(f"[run_tests] changed files: {', '.join(changed)}")
    if targets:
        print(f"[run_tests] selected tests: {', '.join(targets)}")
    else:
        print("[run_tests] executing full test suite.")

    if args.dry_run:
        return 0

    env = prepare_environment()
    clear_previous_artifacts()

    pytest_args = [
        "--json-report",
        f"--json-report-file={REPORT_PATH}",
        f"--benchmark-json={BENCHMARK_PATH}"
    ]
    if args.markers:
        for marker in args.markers:
            pytest_args.extend(["-m", marker])
    if args.parallel:
        pytest_args.extend(["-n", args.workers or "auto"])
    extra = args.pytest_args or []
    if extra and extra[0] == "--":
        extra = extra[1:]
    pytest_args.extend(extra)

    if args.watch:
        return run_watch_mode(pytest_args, targets, env)

    base_cmd = [sys.executable, "-m", "coverage", "run", "-m", "pytest", *pytest_args, *targets]
    pytest_proc = run(base_cmd, env=env)
    coverage_proc = run([sys.executable, "-m", "coverage", "json", "-o", str(COVERAGE_PATH)], env=env)

    ensure_artifact(REPORT_PATH, {"tests": [], "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0}})
    ensure_artifact(BENCHMARK_PATH, {"benchmarks": []})
    ensure_artifact(COVERAGE_PATH, {"meta": {}, "totals": {"percent_covered": 0.0}})

    gate_passed, threshold_ms, breaches = enforce_performance_gate(args.perf_threshold, args.no_perf_gate)
    if not gate_passed:
        for breach in breaches:
            print(f"[run_tests] PERFORMANCE REGRESSION: {breach}")
    exit_code = pytest_proc.returncode or 0
    if coverage_proc.returncode not in (0, None):
        exit_code = exit_code or coverage_proc.returncode
    if not gate_passed and not args.no_perf_gate:
        exit_code = exit_code or 1

    gates_payload = {
        "pytest": {
            "exit_code": pytest_proc.returncode,
            "coverage_exit_code": coverage_proc.returncode,
            "selected_tests": targets,
            "scope": args.scope,
            "reason": reason,
            "changed_files": changed,
        },
        "performance": {
            "threshold_ms": threshold_ms,
            "breaches": breaches,
            "passed": gate_passed,
        },
    }
    try:
        GATES_PATH.write_text(json.dumps(gates_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[run_tests] failed to write {GATES_PATH}: {exc}")

    if exit_code == 0:
        print("[run_tests] Tests completed successfully.")
    else:
        print(f"[run_tests] Test run finished with exit code {exit_code}.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
