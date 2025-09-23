from __future__ import annotations

"""سیستم تست تطبیقی با حالت‌های مختلف پیچیدگی.
Adaptive testing system with selectable complexity modes and security depth.
"""

import argparse
import asyncio
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:  # GitPython is optional but recommended
    import git
except Exception:  # pragma: no cover - graceful fallback when not installed
    git = None

ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
HISTORY_DIR = LOGS_DIR / "adaptive_history"
DEFAULT_CONFIG_PATH = ROOT / ".test-config.json"


class TestingMode(Enum):
    """حالت‌های اجرای تست / Supported testing modes."""

    QUICK = "quick"        # تست‌های سریع برای توسعه روزانه / quick feedback for dev loop
    STANDARD = "standard"  # تست‌های استاندارد به همراه پوشش / pytest + coverage
    DEEP = "deep"          # تست‌های عمیق با mutation / adds mutation analysis
    SECURITY = "security"  # تمرکز بر امنیت / security-focused scans
    FULL = "full"          # همه تست‌ها / full pipeline with AI + security


@dataclass(slots=True)
class CommandResult:
    """نتایج اجرای دستورات پوسته / Captured subprocess outcome."""

    command: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    duration: float

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


class AdaptiveTester:
    """کلاس تست تطبیقی هوشمند / Orchestrates adaptive test execution."""

    def __init__(self, mode: TestingMode = TestingMode.STANDARD, config_path: Path | None = None) -> None:
        self.mode = mode
        self.config = self._load_config(config_path)
        self.repo = self._load_repo()

    def _load_config(self, config_path: Path | None) -> Dict[str, Any]:
        """بارگذاری تنظیمات از فایل پیکربندی.

        Load optional JSON configuration for thresholds and toggles.
        """

        path = config_path or DEFAULT_CONFIG_PATH
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"[adaptive] failed to parse {path}: {exc}")
        return {
            "mutation_threshold": 90,
            "coverage_threshold": 80,
            "security_enabled": True,
            "ml_predictions": True,
            "results_limit": 20,
        }

    def _load_repo(self) -> Optional[git.Repo]:
        if git is None:
            print("[adaptive] GitPython not available; falling back to filesystem scan")
            return None
        try:
            return git.Repo(ROOT)
        except Exception as exc:
            print(f"[adaptive] unable to load git repo: {exc}")
            return None

    async def detect_changed_files(self) -> List[str]:
        """تشخیص فایل‌های تغییر یافته / Detect changed Python files since last commit."""

        if self.repo is None:
            return [str(path.relative_to(ROOT)) for path in (ROOT / "src").rglob("*.py")]
        try:
            diff_index = self.repo.index.diff(None)
            changed: set[str] = set()
            for item in diff_index:
                candidate = item.a_path or item.b_path
                if candidate and candidate.endswith(".py"):
                    changed.add(candidate)
            untracked = [f for f in self.repo.untracked_files if f.endswith(".py")]
            changed.update(untracked)
            if not changed:
                # fallback to compare with HEAD
                head = self.repo.head.commit
                for item in head.diff(None):
                    candidate = item.a_path or item.b_path
                    if candidate and candidate.endswith(".py"):
                        changed.add(candidate)
            return sorted(changed)
        except Exception as exc:
            print(f"[adaptive] git diff detection failed: {exc}")
            return [str(path.relative_to(ROOT)) for path in (ROOT / "src").rglob("*.py")]

    async def run_adaptive_tests(self) -> Dict[str, Any]:
        """اجرای تست‌های تطبیقی بر اساس حالت انتخابی."""

        started_at = datetime.now(timezone.utc)
        results: Dict[str, Any] = {
            "mode": self.mode.value,
            "timestamp": started_at.isoformat(),
            "changed_files": await self.detect_changed_files(),
            "tests_run": [],
            "metrics": {},
            "warnings": [],
        }

        if self.mode == TestingMode.QUICK:
            await self._run_quick_tests(results)
        elif self.mode == TestingMode.STANDARD:
            await self._run_standard_tests(results)
        elif self.mode == TestingMode.DEEP:
            await self._run_standard_tests(results)
            await self._run_mutation_tests(results)
        elif self.mode == TestingMode.SECURITY:
            await self._run_security_tests(results)
        elif self.mode == TestingMode.FULL:
            await self._run_standard_tests(results)
            await self._run_mutation_tests(results)
            await self._run_security_tests(results)

        await self._save_results(results)
        return results

    async def _run_quick_tests(self, results: Dict[str, Any]) -> None:
        """تست‌های سریع فقط برای فایل‌های تغییر یافته."""

        changed = results.get("changed_files", [])
        if not changed:
            results["warnings"].append("no python files changed; skipped quick tests")
            return

        targets = await self._map_tests_for_sources(changed)
        if not targets:
            results["warnings"].append("no mapped tests for changed files; consider running standard suite")
            return

        cmd = ["pytest", *targets, "-vv", "--maxfail=1", "--disable-warnings"]
        outcome = await self._execute(cmd)
        results["tests_run"].append({
            "type": "quick",
            "command": cmd,
            "returncode": outcome.returncode,
            "files": targets,
        })

    async def _run_standard_tests(self, results: Dict[str, Any]) -> None:
        """اجرای pytest با گزارش پوشش."""

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        coverage_path = LOGS_DIR / "coverage.xml"
        junit_path = LOGS_DIR / "junit.xml"
        json_report = LOGS_DIR / "pytest-report.json"

        cmd = [
            "pytest",
            "-xvv",
            "--maxfail=1",
            "--cov=src",
            f"--cov-report=xml:{coverage_path}",
            f"--junitxml={junit_path}",
            "--json-report",
            f"--json-report-file={json_report}",
        ]
        outcome = await self._execute(cmd)
        results["tests_run"].append({
            "type": "standard",
            "command": cmd,
            "returncode": outcome.returncode,
        })
        if coverage_path.exists():
            results["metrics"]["coverage_report"] = coverage_path.as_posix()
        if json_report.exists():
            try:
                payload = json.loads(json_report.read_text(encoding="utf-8"))
                totals = payload.get("summary", {})
                coverage_percent = self._extract_coverage_percentage(coverage_path)
                results["metrics"].update({
                    "tests_total": totals.get("total", 0),
                    "tests_failed": totals.get("failed", 0),
                    "tests_xfailed": totals.get("xfailed", 0),
                    "tests_xpassed": totals.get("xpassed", 0),
                    "coverage_percent": coverage_percent,
                })
                if coverage_percent is not None:
                    threshold = float(self.config.get("coverage_threshold", 80))
                    results["metrics"]["coverage_status"] = (
                        "passed" if coverage_percent >= threshold else "needs_attention"
                    )
            except Exception as exc:  # noqa: BLE001
                results["warnings"].append(f"failed to parse pytest json report: {exc}")

    async def _run_mutation_tests(self, results: Dict[str, Any]) -> None:
        """اجرای mutation testing برای فایل‌های تغییر یافته."""

        changed = [path for path in results.get("changed_files", []) if path.startswith("src/")]
        if not changed:
            results["warnings"].append("no changed source files; skipping mutation analysis")
            return

        targets = changed[: self.config.get("mutation_target_limit", 3)]
        runner = "python -m pytest -x"
        aggregated: List[CommandResult] = []
        for target in targets:
            cmd = [
                "mutmut",
                "run",
                "--paths-to-mutate",
                target,
                "--runner",
                runner,
            ]
            outcome = await self._execute(cmd, timeout=self.config.get("mutation_timeout", 600))
            aggregated.append(outcome)

        report = await self._execute(["mutmut", "results"], allow_missing=True)
        if report.returncode != 0:
            results["metrics"]["mutation"] = {
                "status": "unavailable",
                "reason": report.stderr.strip() or "mutmut not installed",
                "targets": targets,
            }
            return

        mut_metrics = self._parse_mutmut_results(report.stdout)
        mut_metrics["targets"] = targets
        mut_metrics["commands"] = [list(res.command) for res in aggregated]
        results["metrics"]["mutation"] = mut_metrics

    async def _run_security_tests(self, results: Dict[str, Any]) -> None:
        """اجرای تست‌های امنیتی شامل Bandit و Safety و تست‌های سفارشی."""

        metrics: Dict[str, Any] = {}

        bandit = await self._execute(["bandit", "-r", "src", "-f", "json", "-ll"], allow_missing=True)
        if bandit.succeeded:
            try:
                bandit_payload = json.loads(bandit.stdout or "{}")
                metrics["bandit"] = {
                    "issues": len(bandit_payload.get("results", [])),
                    "severity": self._categorize_security_issues(bandit_payload),
                }
            except json.JSONDecodeError as exc:
                results["warnings"].append(f"bandit json parse error: {exc}")
        else:
            metrics["bandit"] = {"error": bandit.stderr.strip() or "bandit failed"}

        safety = await self._execute(["safety", "check", "--json"], allow_missing=True)
        if safety.succeeded:
            try:
                deps = json.loads(safety.stdout or "[]")
                metrics["dependencies"] = {
                    "vulnerabilities": len(deps),
                    "status": "secure" if not deps else "vulnerable",
                }
            except json.JSONDecodeError as exc:
                results["warnings"].append(f"safety json parse error: {exc}")
        else:
            metrics["dependencies"] = {"error": safety.stderr.strip() or "safety failed"}

        persian_security = await self._execute([
            "pytest",
            "tests/test_security.py",
            "-vv",
            "-k",
            "persian",
        ], allow_missing=True)
        metrics["persian_suite"] = {
            "returncode": persian_security.returncode,
            "passed": persian_security.returncode == 0,
            "details": "see pytest output",
        }

        results["metrics"]["security"] = metrics

    async def _save_results(self, results: Dict[str, Any]) -> None:
        """ذخیره نتایج در مسیر لاگ برای استفاده در داشبورد."""

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = HISTORY_DIR / f"adaptive_{timestamp}.json"
        latest_path = LOGS_DIR / "adaptive_latest.json"
        payload = json.dumps(results, ensure_ascii=False, indent=2)
        snapshot_path.write_text(payload, encoding="utf-8")
        latest_path.write_text(payload, encoding="utf-8")

        # Trim history if configured
        limit = int(self.config.get("results_limit", 20))
        snapshots = sorted(HISTORY_DIR.glob("adaptive_*.json"))
        while len(snapshots) > limit:
            victim = snapshots.pop(0)
            try:
                victim.unlink()
            except OSError:
                break

    async def _map_tests_for_sources(self, changed: Iterable[str]) -> List[str]:
        """نقشه‌برداری فایل‌های منبع به فایل‌های تست."""

        try:
            from scripts import run_tests  # imported lazily to avoid cycles
        except Exception:
            run_tests = None  # type: ignore

        if run_tests:
            mapped = run_tests.compute_tests_from_changes(changed)
            if mapped:
                return mapped
        # fallback heuristic: map src/foo.py -> tests/test_foo.py
        targets: List[str] = []
        for path in changed:
            if not path.startswith("src/"):
                continue
            candidate = path.replace("src/", "tests/test_")
            candidate_path = ROOT / candidate
            if candidate_path.exists():
                targets.append(candidate_path.relative_to(ROOT).as_posix())
        return sorted(set(targets))

    async def _execute(self, cmd: Sequence[str], *, timeout: Optional[int] = None, allow_missing: bool = False) -> CommandResult:
        """اجرای مطمئن دستورات پوسته با ثبت خروجی."""

        start = asyncio.get_event_loop().time()

        def runner() -> subprocess.CompletedProcess:
            try:
                return subprocess.run(
                    cmd,
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except FileNotFoundError as exc:
                if allow_missing:
                    cp = subprocess.CompletedProcess(cmd, 127, "", str(exc))
                    return cp
                raise

        try:
            completed = await asyncio.to_thread(runner)
        except FileNotFoundError as exc:
            print(f"[adaptive] command not found: {cmd[0]} ({exc})")
            return CommandResult(cmd, 127, "", str(exc), 0.0)
        except subprocess.TimeoutExpired as exc:
            print(f"[adaptive] timeout: {cmd}")
            return CommandResult(cmd, 124, exc.stdout or "", exc.stderr or "timeout", timeout or 0.0)

        duration = asyncio.get_event_loop().time() - start
        if completed.returncode != 0 and not allow_missing:
            print(f"[adaptive] command failed ({completed.returncode}): {' '.join(cmd)}")
        return CommandResult(cmd, completed.returncode, completed.stdout or "", completed.stderr or "", duration)

    def _extract_coverage_percentage(self, coverage_path: Path) -> Optional[float]:
        try:
            from xml.etree import ElementTree as ET

            tree = ET.fromstring(coverage_path.read_text(encoding="utf-8"))
            totals = tree.attrib
            lines_valid = float(totals.get("lines-valid", 0.0))
            lines_covered = float(totals.get("lines-covered", 0.0))
            if lines_valid == 0:
                return None
            percent = round(lines_covered / lines_valid * 100, 2)
            return percent
        except Exception as exc:  # noqa: BLE001
            print(f"[adaptive] coverage parsing failed: {exc}")
            return None

    def _parse_mutmut_results(self, stdout: str) -> Dict[str, Any]:
        lines = (stdout or "").splitlines()
        killed = survived = 0
        for line in lines:
            if "killed" in line.lower():
                killed = self._extract_leading_int(line)
            elif "survived" in line.lower():
                survived = self._extract_leading_int(line)
        total = killed + survived
        score = round((killed / total * 100), 2) if total else 0.0
        status = "passed" if score >= float(self.config.get("mutation_threshold", 90)) else "needs_improvement"
        return {
            "killed": killed,
            "survived": survived,
            "total": total,
            "score": score,
            "status": status,
        }

    def _extract_leading_int(self, line: str) -> int:
        for token in line.split():
            if token.isdigit():
                return int(token)
        return 0

    def _categorize_security_issues(self, payload: Dict[str, Any]) -> Dict[str, int]:
        severity = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for issue in payload.get("results", []) or []:
            level = (issue.get("issue_severity") or "LOW").upper()
            if level in severity:
                severity[level] += 1
        return severity


async def _async_main(args: argparse.Namespace) -> None:
    tester = AdaptiveTester(TestingMode(args.mode))
    results = await tester.run_adaptive_tests()
    print(json.dumps(results, ensure_ascii=False, indent=2))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adaptive testing orchestrator")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in TestingMode],
        default=TestingMode.STANDARD.value,
        help="انتخاب حالت اجرای تست / Select testing mode",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    asyncio.run(_async_main(args))


if __name__ == "__main__":  # pragma: no cover
    main()
