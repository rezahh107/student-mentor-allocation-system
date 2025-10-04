"""Pytest orchestration compliant with Tailored v2.4."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .bootstrap import BootstrapError
from .evidence import EvidenceLedger, EvidenceResult, verify_evidence
from .fs_atomic import atomic_write_text, ensure_directories, rotate_directory
from .logging_utils import bilingual_message, correlation_id, log_event
from .redis_utils import RedisHandle
from .schemas import validate_pytest_json

PERSIAN_PYTEST_ERROR = "اجرای pytest شکست خورد؛ گزارش‌ها را بررسی کنید."
PERSIAN_ARTIFACT_ERROR = "گزارش‌های pytest پیدا نشد؛ مسیر artifacts را بررسی کنید."
PERSIAN_DURATION_ERROR = "مدت اجرای آزمون‌ها از سقف ۴۸۰ ثانیه عبور کرد؛ لطفاً تست‌های کند را علامت‌گذاری کنید."
PERSIAN_COVERAGE_ERROR = "پوشش کد کمتر از ۸۵٪ است؛ گزارش coverage.xml را بررسی کنید."

MANDATORY_NODEIDS: tuple[str, ...] = (
    "tests/mw/test_order_post.py::test_middleware_order_post_exact",
    "tests/time/test_no_wallclock_repo_guard.py::test_no_wall_clock_calls_in_repo",
    "tests/export/test_csv_excel_hygiene.py::test_formula_guard",
    "tests/security/test_metrics_token_guard.py::test_metrics_requires_token",
    "tests/idem/test_concurrent_posts.py::test_only_one_succeeds",
    "tests/obs/test_retry_metrics.py::test_retry_exhaustion_metrics_present",
    "tests/hygiene/test_state_and_registry.py::test_no_midrun_flush",
    "tests/fixtures/test_state_hygiene.py::test_cleanup_and_registry_reset",
    "tests/export/test_atomic_io.py::test_atomic_io",
    "tests/i18n/test_persian_errors.py::test_persian_error_envelopes",
    "tests/perf/test_perf_gates.py::test_p95_latency_and_memory",
    "tests/ci/test_ci_pytest_runner.py::test_coverage_gate",
    "tests/ci/test_dependency_lock.py::test_constraints_lockfile",
)


@dataclass(frozen=True)
class PytestConfig:
    name: str
    markers: str
    targets: Sequence[str]


@dataclass(frozen=True)
class ArtifactLayout:
    job: str
    root: Path
    test_reports: Path
    coverage_dir: Path
    coverage_html: Path
    security_dir: Path
    strict_dir: Path
    sbom_dir: Path
    pytest_json: Path
    junit_xml: Path
    coverage_xml: Path
    stdout_log: Path
    stderr_log: Path
    metadata_path: Path


@dataclass(frozen=True)
class PytestRunResult:
    config: PytestConfig
    layout: ArtifactLayout
    data: Mapping[str, object]
    duration_seconds: float
    coverage_rate: float
    evidence: EvidenceResult
    executed: set[str]

    @property
    def summary(self) -> Mapping[str, int]:
        summary = self.data.get("summary", {})
        if isinstance(summary, Mapping):
            return {
                "passed": int(summary.get("passed", 0)),
                "failed": int(summary.get("failed", 0)),
                "skipped": int(summary.get("skipped", 0)),
                "xfailed": int(summary.get("xfailed", 0)),
                "warnings": int(summary.get("warnings", 0)),
            }
        return {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "warnings": 0}


LAYER_CONFIG: dict[str, PytestConfig] = {
    "pr": PytestConfig(name="pr", markers="not (slow or perf or e2e or legacy_fixed)", targets=("tests", *MANDATORY_NODEIDS)),
    "full": PytestConfig(name="full", markers="true", targets=("tests",)),
    "smoke": PytestConfig(name="smoke", markers="true", targets=MANDATORY_NODEIDS),
}


def _job_for_layer(layer: str) -> str:
    return "nightly" if layer == "full" else layer


def _build_layout(layer: str) -> ArtifactLayout:
    job = _job_for_layer(layer)
    root = Path("artifacts") / job
    return ArtifactLayout(
        job=job,
        root=root,
        test_reports=root / "test-reports",
        coverage_dir=root / "coverage",
        coverage_html=root / "coverage" / "html",
        security_dir=root / "security",
        strict_dir=root / "strict",
        sbom_dir=root / "sbom",
        pytest_json=root / "test-reports" / "pytest.json",
        junit_xml=root / "test-reports" / "junit.xml",
        coverage_xml=root / "coverage" / "coverage.xml",
        stdout_log=root / "test-reports" / "pytest-stdout.log",
        stderr_log=root / "test-reports" / "pytest-stderr.log",
        metadata_path=root / "run_metadata.json",
    )


def _prepare_layout(layout: ArtifactLayout) -> None:
    rotate_directory(layout.root)
    ensure_directories(
        [
            layout.test_reports,
            layout.coverage_dir,
            layout.coverage_html,
            layout.security_dir,
            layout.strict_dir,
            layout.sbom_dir,
        ]
    )


def _pytest_command(config: PytestConfig, layout: ArtifactLayout, layer: str) -> list[str]:
    workers = os.getenv("PR_WORKERS", "4") if layer == "pr" else os.getenv("FULL_WORKERS", os.getenv("PR_WORKERS", "4"))
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "pytest_asyncio",
        "-p",
        "pytest_cov",
        "-p",
        "pytest_jsonreport",
        "-p",
        "pytest_randomly",
        "-n",
        workers,
        "--dist=loadfile",
        "--maxfail=1",
        "--json-report-file",
        str(layout.pytest_json),
        "--junitxml",
        str(layout.junit_xml),
        "--cov=src",
        "--cov-report=xml:" + str(layout.coverage_xml),
        "--cov-report=html:" + str(layout.coverage_html),
        "--durations=25",
        "-k",
        config.markers,
    ]
    cmd.extend(config.targets)
    return cmd


def _read_pytest_json(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        raise BootstrapError(bilingual_message(PERSIAN_ARTIFACT_ERROR, f"Missing {path}"))
    return validate_pytest_json(path)


def _collect_executed(data: Mapping[str, object]) -> set[str]:
    executed: set[str] = set()
    tests = data.get("tests", [])
    if isinstance(tests, Sequence):
        for item in tests:
            if not isinstance(item, Mapping):
                continue
            nodeid = item.get("nodeid")
            if isinstance(nodeid, str):
                executed.add(nodeid)
    return executed


def _read_coverage(path: Path) -> float:
    if not path.is_file():
        raise BootstrapError(bilingual_message(PERSIAN_ARTIFACT_ERROR, f"Missing {path}"))
    tree = ET.parse(path)
    root = tree.getroot()
    rate = root.attrib.get("line-rate", "0")
    try:
        return float(rate)
    except ValueError:  # pragma: no cover - malformed coverage
        return 0.0


def _store_metadata(layout: ArtifactLayout, duration: float, coverage: float) -> None:
    payload = {
        "duration_seconds": duration,
        "coverage_rate": coverage,
        "correlation_id": correlation_id(),
    }
    atomic_write_text(layout.metadata_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def run_pytest_layer(layer: str, handle: RedisHandle) -> PytestRunResult:
    config = LAYER_CONFIG[layer]
    layout = _build_layout(layer)
    _prepare_layout(layout)

    env = os.environ.copy()
    env.setdefault("TZ", "Asia/Tehran")
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env.setdefault("PYTHONHASHSEED", "0")
    env["REDIS_KEY_PREFIX"] = handle.namespace

    cmd = _pytest_command(config, layout, layer)
    log_event("pytest_start", layer=layer, command=" ".join(cmd))

    start = time.monotonic()
    with open(layout.stdout_log, "w", encoding="utf-8") as stdout, open(
        layout.stderr_log, "w", encoding="utf-8"
    ) as stderr:
        proc = subprocess.run(cmd, stdout=stdout, stderr=stderr, env=env)
    duration = time.monotonic() - start
    log_event("pytest_finished", layer=layer, duration=duration, returncode=proc.returncode)

    if proc.returncode != 0:
        raise BootstrapError(bilingual_message(PERSIAN_PYTEST_ERROR, f"exit code {proc.returncode}"))

    data = _read_pytest_json(layout.pytest_json)
    executed = _collect_executed(data)
    ledger = EvidenceLedger.from_pytest_report(data, executed)
    evidence = verify_evidence(ledger)
    coverage_rate = _read_coverage(layout.coverage_xml)

    if layer == "pr":
        if duration > 480:
            raise BootstrapError(bilingual_message(PERSIAN_DURATION_ERROR, f"duration={duration:.2f}s"))
        if coverage_rate < 0.85:
            raise BootstrapError(bilingual_message(PERSIAN_COVERAGE_ERROR, f"coverage={coverage_rate:.3f}"))

    _store_metadata(layout, duration, coverage_rate)

    return PytestRunResult(
        config=config,
        layout=layout,
        data=data,
        duration_seconds=duration,
        coverage_rate=coverage_rate,
        evidence=evidence,
        executed=executed,
    )


def _load_metadata(layout: ArtifactLayout) -> tuple[float, float]:
    if layout.metadata_path.is_file():
        with open(layout.metadata_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return float(payload.get("duration_seconds", 0.0)), float(payload.get("coverage_rate", 0.0))
    return 0.0, _read_coverage(layout.coverage_xml)


def load_pytest_result(layer: str) -> PytestRunResult:
    config = LAYER_CONFIG[layer]
    layout = _build_layout(layer)
    data = _read_pytest_json(layout.pytest_json)
    executed = _collect_executed(data)
    ledger = EvidenceLedger.from_pytest_report(data, executed)
    evidence = verify_evidence(ledger)
    duration, coverage = _load_metadata(layout)
    return PytestRunResult(
        config=config,
        layout=layout,
        data=data,
        duration_seconds=duration,
        coverage_rate=coverage,
        evidence=evidence,
        executed=executed,
    )


def run_security_checks(layout: ArtifactLayout) -> None:
    ensure_directories([layout.security_dir])
    commands = [
        (
            "pip-audit",
            ["pip-audit", "-f", "json", "-o", str(layout.security_dir / "pip-audit.json")],
        ),
        (
            "bandit",
            [
                "bandit",
                "-q",
                "-r",
                "src",
                "-f",
                "json",
                "-o",
                str(layout.security_dir / "bandit.json"),
            ],
        ),
    ]
    for tool, cmd in commands:
        output_path = Path(cmd[-1]) if cmd[-2] == "-o" else layout.security_dir / f"{tool}.json"
        try:
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"exit {result.returncode}")
            if not output_path.is_file():
                raise RuntimeError("no artifact produced")
        except FileNotFoundError:
            _write_offline(layout.security_dir / f"{tool}.json", tool, "tool not installed")
        except RuntimeError as exc:
            _write_offline(layout.security_dir / f"{tool}.json", tool, str(exc))


def _write_offline(path: Path, tool: str, reason: str) -> None:
    payload = {"status": "offline", "tool": tool, "reason": reason}
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
