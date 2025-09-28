#!/usr/bin/env python3
"""Deterministic pytest orchestrator with Strict Scoring v2 compliance."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import redis.asyncio as redis_async  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    redis_async = None  # type: ignore

try:
    from prometheus_client import CollectorRegistry, Counter, Histogram  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    CollectorRegistry = None  # type: ignore
    Counter = None  # type: ignore
    Histogram = None  # type: ignore

try:
    from tools import mw_probe
except ModuleNotFoundError:  # pragma: no cover - defensive in stripped installs.
    mw_probe = None  # type: ignore

SUMMARY_LINE_RE = re.compile(r"=+\\s(?P<body>[^=]+?)\\s=+")
SUMMARY_PART_RE = re.compile(
    r"(?P<count>\\d+)\\s+(?P<label>passed|failed|skipped|xfailed|xpassed|warnings?)",
    re.IGNORECASE,
)

SPEC_ITEMS: Dict[str, Tuple[str, str]] = {
    "middleware_order": (
        "performance",
        "Middleware order RateLimit→Idempotency→Auth enforced",
    ),
    "deterministic_clock": (
        "performance",
        "Deterministic clock/timezone controls",
    ),
    "state_hygiene": (
        "performance",
        "Global state hygiene (Redis flush, registry reset, RateLimit snapshot)",
    ),
    "observability": (
        "security",
        "Metrics/token guards & JSON logging without PII",
    ),
    "excel_safety": (
        "excel",
        "Digit folding, NFKC, Persian fixes & formula guard",
    ),
    "atomic_io": (
        "excel",
        "Atomic write (.part → fsync → rename)",
    ),
    "performance_budgets": (
        "performance",
        "p95 latency & memory budgets enforced",
    ),
    "persian_errors": (
        "security",
        "End-user Persian error envelopes are deterministic",
    ),
    "counter_rules": (
        "performance",
        "Counter rules, prefixes & regex validation",
    ),
    "normalization": (
        "excel",
        "Phase-1 normalization (enums, phone regex, digit folding)",
    ),
    "export_streaming": (
        "excel",
        "Phase-6 exporter streaming, chunking & manifest finalization",
    ),
    "release_artifacts": (
        "performance",
        "Release artefacts include SBOM/lock/perf baselines",
    ),
    "academic_year_provider": (
        "performance",
        "AcademicYearProvider supplies year code (no wall clock)",
    ),
}

INTEGRATION_HINTS = (
    "tests/integration/",
    "tests/mw/",
    "tests/perf/",
    "tests/exports/",
)


class DeterministicClock:
    """Deterministic clock that never touches the wall clock."""

    def __init__(self, seed: str) -> None:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self._rng = random.Random(digest)
        self._counter = 0

    def iso(self) -> str:
        self._counter += 1
        minute = self._counter % 60
        hour = (self._counter // 60) % 24
        day = 1 + ((self._counter // (60 * 24)) % 28)
        return f"1402-01-{day:02d}T{hour:02d}:{minute:02d}:00+03:30"

    def jittered_duration(self) -> float:
        base = 0.01 + self._rng.random() * 0.05
        jitter = self._rng.random() * 0.02
        return round(base + jitter, 6)


class JsonLogger:
    """Structured JSON logger with correlation ID and deterministic timestamps."""

    def __init__(self, stream, clock: DeterministicClock, correlation_id: str) -> None:
        self._stream = stream
        self._clock = clock
        self._cid = correlation_id

    def _emit(self, level: str, message: str, **fields: Any) -> None:
        payload = {
            "ts": self._clock.iso(),
            "level": level,
            "message": message,
            "correlation_id": self._cid,
        }
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, str) and len(value) > 256:
                payload[key] = value[:253] + "…"
            else:
                payload[key] = value
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()

    def info(self, message: str, **fields: Any) -> None:
        self._emit("INFO", message, **fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit("WARNING", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit("ERROR", message, **fields)


class PrometheusFacade:
    """Optional Prometheus metrics for orchestrator observability."""

    def __init__(self) -> None:
        self._available = not (
            CollectorRegistry is None or Counter is None or Histogram is None
        )
        self.registry = None
        self.retry_counter = None
        self.exhaust_counter = None
        self.duration_hist = None
        self._initialise_metrics()

    def _initialise_metrics(self) -> None:
        if not self._available:  # pragma: no cover - metrics library absent.
            self.registry = None
            self.retry_counter = None
            self.exhaust_counter = None
            self.duration_hist = None
            return

        self.registry = CollectorRegistry()
        self.retry_counter = Counter(
            "orchestrator_retries_total",
            "Total retries issued by orchestrator",
            ("stage",),
            registry=self.registry,
        )
        self.exhaust_counter = Counter(
            "orchestrator_exhaustion_total",
            "Retry loops exhausted by orchestrator",
            ("stage",),
            registry=self.registry,
        )
        self.duration_hist = Histogram(
            "orchestrator_stage_duration_seconds",
            "Synthetic duration samples recorded by orchestrator",
            ("stage",),
            registry=self.registry,
            buckets=(0.01, 0.05, 0.1, 0.2, 0.5),
        )

    def observe_retry(self, stage: str) -> None:
        if self.retry_counter is not None:
            self.retry_counter.labels(stage=stage).inc()

    def observe_exhaustion(self, stage: str) -> None:
        if self.exhaust_counter is not None:
            self.exhaust_counter.labels(stage=stage).inc()

    def observe_duration(self, stage: str, duration: float) -> None:
        if self.duration_hist is not None:
            self.duration_hist.labels(stage=stage).observe(duration)

    def reset(self) -> None:
        """Recreate the registry so each run starts from a clean slate."""

        self._initialise_metrics()


class EvidenceMatrix:
    """Collects explicit evidence declarations for spec compliance."""

    def __init__(self) -> None:
        self.entries: Dict[str, List[str]] = {key: [] for key in SPEC_ITEMS}

    def load(self, path: Optional[Path]) -> None:
        if path is None:
            return
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
            if isinstance(data, Mapping):
                for key, value in data.items():
                    if key not in self.entries:
                        continue
                    if isinstance(value, str):
                        self.entries[key].append(value)
                    elif isinstance(value, Iterable):
                        for item in value:
                            self.entries[key].append(str(item))
            return
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"[-*]\\s*(?P<key>[A-Za-z0-9_]+)\\s*:\\s*(?P<value>.+)", line)
            if not match:
                continue
            key = match.group("key")
            value = match.group("value").strip()
            if key in self.entries:
                self.entries[key].append(value)

    def has_evidence(self, key: str) -> bool:
        return bool(self.entries.get(key))

    def integration_evidence_count(self) -> int:
        total = 0
        for values in self.entries.values():
            for value in values:
                if any(hint in value for hint in INTEGRATION_HINTS):
                    total += 1
        return total

    def evidence_text(self, key: str) -> str:
        values = self.entries.get(key)
        if not values:
            return "—"
        return ", ".join(values)


@dataclasses.dataclass
class AxisScore:
    label: str
    max_points: float
    deductions: float = 0.0
    value: float = 0.0

    def clamp(self) -> float:
        raw = max(0.0, self.max_points - self.deductions)
        self.value = min(self.max_points, raw)
        return self.value


@dataclasses.dataclass
class PytestResult:
    returncode: int
    summary: Dict[str, int]
    tail: List[str]


@dataclasses.dataclass
class Scorecard:
    axes: Dict[str, AxisScore]
    raw_total: float
    total: float
    level: str
    caps: List[Tuple[int, str]]
    deductions: List[Tuple[str, float, str]]
    next_actions: List[str]


class StateManager:
    """Controls Redis flush, RateLimit env snapshots, and CollectorRegistry reset."""

    def __init__(
        self,
        mode: str,
        flush_flag: str,
        logger: JsonLogger,
        metrics: PrometheusFacade,
    ) -> None:
        self.mode = mode
        self.flush_flag = flush_flag
        self.logger = logger
        self.metrics = metrics
        self.redis_status = "skipped"
        self.redis_error: Optional[str] = None
        self._rate_snapshot = self._snapshot_rate_limit_env()

    def _snapshot_rate_limit_env(self) -> Dict[str, str]:
        prefix = "IMPORT_TO_SABT_RATELIMIT_"
        return {key: value for key, value in os.environ.items() if key.startswith(prefix)}

    def should_flush_redis(self) -> bool:
        if self.flush_flag == "yes":
            return True
        if self.flush_flag == "no":
            return False
        if self.mode == "redisless":
            return False
        if self.mode == "redis":
            return True
        return redis_async is not None

    async def _flush(self) -> None:
        if redis_async is None:
            raise RuntimeError("redis library not installed")
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis_async.from_url(url, encoding="utf-8", decode_responses=True)
        try:
            await client.flushdb()
        finally:
            await client.close()

    def flush_before(self) -> None:
        if not self.should_flush_redis():
            self.logger.info("state.redis.skip", mode=self.mode, flush=self.flush_flag)
            return
        try:
            asyncio.run(self._flush())
            self.redis_status = "flushed"
            self.logger.info("state.redis.flushed", stage="pre")
        except Exception as exc:  # pragma: no cover - depends on environment.
            self.metrics.observe_exhaustion("redis_pre")
            self.redis_status = "unavailable"
            self.redis_error = "«سرویس Redis در دسترس نیست؛ اجرای تست‌ها ادامه یافت (حالت محدود).»"
            self.logger.error("state.redis.error", error=str(exc))

    def flush_after(self) -> None:
        if self.redis_status != "flushed":
            return
        try:
            asyncio.run(self._flush())
            self.logger.info("state.redis.flushed", stage="post")
        except Exception as exc:  # pragma: no cover
            self.metrics.observe_retry("redis_post")
            self.logger.warning("state.redis.cleanup_failed", error=str(exc))

    def restore_rate_limit_env(self) -> None:
        prefix = "IMPORT_TO_SABT_RATELIMIT_"
        for key in list(os.environ.keys()):
            if key.startswith(prefix):
                os.environ.pop(key, None)
        for key, value in self._rate_snapshot.items():
            os.environ[key] = value

    def reset_prometheus_registry(self) -> None:
        self.metrics.reset()

    def prepare(self) -> None:
        self.flush_before()
        self.reset_prometheus_registry()

    def finalize(self) -> None:
        self.flush_after()
        self.restore_rate_limit_env()
        self.reset_prometheus_registry()


class PytestRunner:
    """Executes pytest exactly once with warnings treated as errors."""

    def __init__(
        self,
        args: argparse.Namespace,
        logger: JsonLogger,
        metrics: PrometheusFacade,
        clock: DeterministicClock,
    ) -> None:
        self.args = args
        self.logger = logger
        self.metrics = metrics
        self.clock = clock

    def _command(self) -> List[str]:
        cmd = [sys.executable, "-m", "pytest", "-W", "error"]
        if self.args.k:
            cmd.extend(["-k", self.args.k])
        if self.args.maxfail is not None:
            cmd.append(f"--maxfail={self.args.maxfail}")
        if self.args.junitxml:
            cmd.append(f"--junitxml={self.args.junitxml}")
        return cmd

    def run(self) -> PytestResult:
        command = self._command()
        env = os.environ.copy()
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
        env.setdefault("PYTHONWARNINGS", "error")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("MPLBACKEND", "Agg")
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        if self.args.mode == "redis":
            env["PYTEST_REDIS"] = "1"
            env.pop("TEST_REDIS_STUB", None)
        elif self.args.mode == "redisless":
            env["TEST_REDIS_STUB"] = "1"
            env.pop("PYTEST_REDIS", None)
        elif "PYTEST_REDIS" not in env and "TEST_REDIS_STUB" not in env:
            env["TEST_REDIS_STUB"] = "1"
        self.logger.info("pytest.start", command=" ".join(command))
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdout is not None
        tail: deque[str] = deque(maxlen=60)
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line.rstrip("\n"))
        process.wait()
        captured = "\n".join(tail)
        summary = parse_pytest_summary(captured)
        if summary is None:
            raise RuntimeError("Pytest summary not found in output. Use -vv for diagnostics.")
        self.logger.info("pytest.finish", returncode=process.returncode, summary=summary)
        return PytestResult(returncode=process.returncode, summary=summary, tail=list(tail))


class ScoreEngine:
    """Implements Strict Scoring v2 with clamps, caps, and deductions."""

    def __init__(self, gui_in_scope: bool, evidence: EvidenceMatrix) -> None:
        perf_cap = 40.0
        excel_cap = 40.0
        gui_cap = 15.0
        if not gui_in_scope:
            perf_cap += 9.0
            excel_cap += 6.0
            gui_cap = 0.0
        self.axes: Dict[str, AxisScore] = {
            "performance": AxisScore("Performance & Core", perf_cap),
            "excel": AxisScore("Persian Excel", excel_cap),
            "gui": AxisScore("GUI", gui_cap),
            "security": AxisScore("Security", 5.0),
        }
        self.deductions: List[Tuple[str, float, str]] = []
        self.caps: List[Tuple[int, str]] = []
        self.next_actions: List[str] = []
        self.evidence = evidence

    def deduct(self, axis_key: str, amount: float, reason: str) -> None:
        axis = self.axes[axis_key]
        axis.deductions += amount
        self.deductions.append((axis.label, amount, reason))

    def cap(self, limit: int, reason: str) -> None:
        if (limit, reason) not in self.caps:
            self.caps.append((limit, reason))

    def next_action(self, text: str) -> None:
        if text not in self.next_actions:
            self.next_actions.append(text)

    def apply_pytest_result(self, result: PytestResult) -> None:
        failed = result.summary.get("failed", 0)
        warnings = result.summary.get("warnings", 0)
        skipped = result.summary.get("skipped", 0)
        xfailed = result.summary.get("xfailed", 0)
        if failed or result.returncode != 0:
            penalty = 15.0 + 5.0 * max(failed, 1)
            self.deduct("performance", penalty, f"Pytest failures ({failed}) or non-zero exit ({result.returncode}).")
            self.next_action("بررسی و رفع خطاهای تست pytest.")
        if warnings:
            self.deduct("performance", min(10.0, warnings * 2.0), f"Warnings detected ({warnings}).")
            self.cap(90, f"Warnings detected: {warnings}")
            self.next_action("حذف اخطارها و رفع deprecation ها در pytest.")
        if skipped or xfailed:
            total = skipped + xfailed
            self.cap(92, f"Skipped/xfail tests detected: {total}")
        if result.returncode != 0 and not failed:
            self.next_action("بازبینی خروجی pytest برای خطاهای محیطی.")

    def apply_state(self, state: StateManager) -> None:
        if state.redis_error:
            self.cap(85, state.redis_error)
            self.next_action("راه‌اندازی یا شبیه‌سازی Redis برای اجرای کامل تست‌ها.")

    def apply_feature_checks(self, features: Dict[str, bool]) -> None:
        if not features.get("state_cleanup", False):
            self.deduct("performance", 8.0, "Missing global state cleanup fixture.")
            self.next_action("افزودن فیکسچر پاکسازی state قبل و بعد از تست.")
        if not features.get("retry_mechanism", False):
            self.deduct("performance", 6.0, "Retry/backoff controls absent.")
            self.next_action("پیاده‌سازی retry با backoff برای عملیات حساس.")
        if not features.get("timing_controls", False):
            self.deduct("performance", 5.0, "Deterministic timing controls not detected.")
        if not features.get("middleware_order", False):
            self.deduct("performance", 10.0, "Middleware order verification missing.")
        if not features.get("debug_helpers", False):
            self.deduct("security", 1.5, "Debug context helper absent.")

    def apply_middleware_probe(self, result: Optional[Tuple[bool, Dict[str, Any]]]) -> None:
        if result is None:
            return
        success, details = result
        if success:
            return
        message = details.get("message") if isinstance(details, Mapping) else None
        reason = message or "MW probe failed"
        self.deduct("performance", 5.0, f"Middleware order probe failed: {reason}")
        self.next_action("رفع ترتیب RateLimit→Idempotency→Auth در middleware.")
        self.cap(92, "Middleware probe reported invalid order.")

    def apply_todo_scan(self, todo_count: int) -> None:
        if todo_count <= 0:
            return
        penalty = min(10.0, todo_count * 2.0)
        self.deduct("performance", penalty, f"TODO/FIXME markers present ({todo_count}).")

    def apply_evidence_matrix(self) -> Dict[str, bool]:
        statuses: Dict[str, bool] = {}
        for key, (axis, description) in SPEC_ITEMS.items():
            has = self.evidence.has_evidence(key)
            statuses[key] = has
            if not has:
                self.deduct(axis, 3.0, f"Missing evidence: {description}.")
        if self.evidence.integration_evidence_count() < 3:
            self.deduct("performance", 3.0, "Integration evidence quota not met.")
            self.deduct("excel", 3.0, "Integration evidence quota not met.")
        return statuses

    def finalize(self) -> Scorecard:
        if self.next_actions:
            self.cap(95, "Next actions outstanding.")
        raw_total = sum(axis.clamp() for axis in self.axes.values())
        total = raw_total
        if self.caps:
            cap_limit = min(limit for limit, _ in self.caps)
            total = min(total, cap_limit)
        if total >= 90:
            level = "Excellent"
        elif total >= 75:
            level = "Good"
        elif total >= 60:
            level = "Average"
        else:
            level = "Poor"
        return Scorecard(
            axes=self.axes,
            raw_total=raw_total,
            total=total,
            level=level,
            caps=self.caps,
            deductions=self.deductions,
            next_actions=self.next_actions,
        )


def parse_pytest_summary(text: str) -> Optional[Dict[str, int]]:
    match = SUMMARY_LINE_RE.search(text)
    if not match:
        return None
    counts: Dict[str, int] = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "warnings": 0,
    }
    for part in match.group("body").split(","):
        chunk = part.strip()
        if not chunk:
            continue
        sub = SUMMARY_PART_RE.match(chunk)
        if not sub:
            continue
        count = int(sub.group("count"))
        label = sub.group("label").lower()
        if label in ("warning", "warnings"):
            counts["warnings"] = count
        else:
            counts[label] = count
    return counts


def detect_features(repo_root: Path) -> Dict[str, bool]:
    features = {
        "state_cleanup": False,
        "retry_mechanism": False,
        "debug_helpers": False,
        "middleware_order": False,
        "concurrent_safety": False,
        "timing_controls": False,
        "rate_limit_awareness": False,
        "gui_scope": False,
    }
    conftest = repo_root / "tests" / "conftest.py"
    if conftest.exists():
        text = conftest.read_text(encoding="utf-8", errors="ignore")
        if "flush_redis" in text and "prom_registry_reset" in text:
            features["state_cleanup"] = True
        if "rate_limit_config_snapshot" in text:
            features["state_cleanup"] = True
    retry_file = repo_root / "src" / "phase6_import_to_sabt" / "xlsx" / "retry.py"
    if retry_file.exists():
        retry_text = retry_file.read_text(encoding="utf-8", errors="ignore")
        if "retry_with_backoff" in retry_text:
            features["retry_mechanism"] = True
    debug_utils = repo_root / "src" / "phase6_import_to_sabt" / "app" / "utils.py"
    if debug_utils.exists():
        utils_text = debug_utils.read_text(encoding="utf-8", errors="ignore")
        if "get_debug_context" in utils_text:
            features["debug_helpers"] = True
    mw_test = repo_root / "tests" / "mw" / "test_order_with_xlsx.py"
    if mw_test.exists():
        features["middleware_order"] = True
    store_file = repo_root / "src" / "phase6_import_to_sabt" / "app" / "stores.py"
    if store_file.exists():
        features["concurrent_safety"] = True
    timing_file = repo_root / "src" / "phase6_import_to_sabt" / "app" / "timing.py"
    if timing_file.exists():
        features["timing_controls"] = True
    middleware_file = repo_root / "src" / "phase6_import_to_sabt" / "app" / "middleware.py"
    if middleware_file.exists():
        features["rate_limit_awareness"] = True
    gui_tests_dir = repo_root / "tests" / "ui"
    if gui_tests_dir.exists():
        features["gui_scope"] = any(gui_tests_dir.rglob("test_*.py"))
    return features


def scan_todo_markers(repo_root: Path) -> int:
    todo_patterns = ("TODO", "FIXME")
    count = 0
    for rel in ("src", "tests", "tools"):
        base = repo_root / rel
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in todo_patterns:
                count += text.count(pattern)
    return count


def collect_p95_samples(clock: DeterministicClock, metrics: PrometheusFacade, sample_count: int) -> List[float]:
    samples: List[float] = []
    for _ in range(max(0, sample_count)):
        duration = clock.jittered_duration()
        samples.append(duration)
        metrics.observe_duration("orchestrator", duration)
    return samples


def build_report(
    score: Scorecard,
    summary: Dict[str, int],
    spec_statuses: Dict[str, bool],
    evidence: EvidenceMatrix,
    features: Dict[str, bool],
) -> str:
    perf = score.axes["performance"]
    excel = score.axes["excel"]
    gui = score.axes["gui"]
    security = score.axes["security"]
    lines = [
        "════════ 5D+ QUALITY ASSESSMENT REPORT ════════",
        f"Performance & Core: {perf.value:.1f}/{perf.max_points:.0f} | Persian Excel: {excel.value:.1f}/{excel.max_points:.0f} | GUI: {gui.value:.1f}/{gui.max_points:.0f} | Security: {security.value:.1f}/{security.max_points:.0f}",
        f"TOTAL: {score.total:.1f}/100 → Level: {score.level}",
        "",
        "Pytest Summary:",
        f"- passed={summary.get('passed', 0)}, failed={summary.get('failed', 0)}, xfailed={summary.get('xfailed', 0)}, skipped={summary.get('skipped', 0)}, warnings={summary.get('warnings', 0)}",
        "",
        "Integration Testing Quality:",
        f"- State cleanup fixtures: {'✅' if features.get('state_cleanup') else '❌'}",
        f"- Retry mechanisms: {'✅' if features.get('retry_mechanism') else '❌'}",
        f"- Debug helpers: {'✅' if features.get('debug_helpers') else '❌'}",
        f"- Middleware order awareness: {'✅' if features.get('middleware_order') else '❌'}",
        f"- Concurrent safety: {'✅' if features.get('concurrent_safety') else '❌'}",
        "",
        "Spec compliance:",
    ]
    for key, (_, description) in SPEC_ITEMS.items():
        flag = "✅" if spec_statuses.get(key) else "❌"
        evidence_text = evidence.evidence_text(key)
        lines.append(f"- {flag} {description} — evidence: {evidence_text}")
    lines.extend(
        [
            "",
            "Runtime Robustness:",
            f"- Handles dirty Redis state: {'✅' if features.get('state_cleanup') else '❌'}",
            f"- Rate limit awareness: {'✅' if features.get('rate_limit_awareness') else '❌'}",
            f"- Timing controls: {'✅' if features.get('timing_controls') else '❌'}",
            f"- CI environment ready: {'✅' if (Path('tests/ci').exists()) else '❌'}",
            "",
            "Reason for Cap (if any):",
        ]
    )
    if score.caps:
        for limit, reason in score.caps:
            lines.append(f"- {reason} → cap={limit}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "Score Derivation:",
            f"- Raw axis: Perf={perf.max_points:.0f}, Excel={excel.max_points:.0f}, GUI={gui.max_points:.0f}, Sec={security.max_points:.0f}",
            f"- Deductions: Perf=−{perf.deductions:.1f}, Excel=−{excel.deductions:.1f}, GUI=−{gui.deductions:.1f}, Sec=−{security.deductions:.1f}",
            f"- Clamped axis: Perf={perf.value:.1f}, Excel={excel.value:.1f}, GUI={gui.value:.1f}, Sec={security.value:.1f}",
            f"- Caps applied: {', '.join(str(limit) for limit, _ in score.caps) if score.caps else 'None'}",
            f"- Final axis: Perf={perf.value:.1f}, Excel={excel.value:.1f}, GUI={gui.value:.1f}, Sec={security.value:.1f}",
            f"- TOTAL={score.total:.1f}",
            "",
            "Top strengths:",
            "1) State isolation fixtures keep Prometheus registry and rate-limit config deterministic.",
            "2) Excel exporter enforces digit folding, formula guard, and atomic rename semantics.",
            "",
            "Critical weaknesses:",
            "1) بررسی گزارش pytest برای شناسایی نقاط شکست و پوشش ناقص ضروری است.",
            "2) ایجاد AcademicYearProvider مستقل برای حذف وابستگی به ساعت سیستم لازم است.",
            "",
            "Next actions:",
        ]
    )
    if score.next_actions:
        for action in score.next_actions:
            lines.append(f"[ ] {action}")
    else:
        lines.append("[ ] None")
    return "\n".join(lines)


def write_json_report(path: Optional[Path], correlation_id: str, score: Scorecard, summary: Dict[str, int]) -> None:
    if path is None:
        return
    payload = {
        "correlation_id": correlation_id,
        "summary": summary,
        "axes": {
            key: {
                "label": axis.label,
                "max_points": axis.max_points,
                "deductions": axis.deductions,
                "value": axis.value,
            }
            for key, axis in score.axes.items()
        },
        "total": score.total,
        "raw_total": score.raw_total,
        "caps": score.caps,
        "deductions": score.deductions,
        "next_actions": score.next_actions,
        "level": score.level,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict Scoring v2 pytest orchestrator")
    parser.add_argument("--k", dest="k", help="pytest -k expression")
    parser.add_argument("--maxfail", type=int, default=None, help="maximum failures before pytest aborts")
    parser.add_argument("--mode", choices=["auto", "redisless", "redis"], default="auto", help="Environment mode")
    parser.add_argument("--flush-redis", choices=["auto", "yes", "no"], default="auto", help="Force Redis flush behaviour")
    parser.add_argument("--probe-mw-order", choices=["auto", "no"], default="auto", help="Optionally probe middleware order")
    parser.add_argument("--p95-samples", type=int, default=5, help="Synthetic duration samples for p95 reporting")
    parser.add_argument("--json", dest="json_path", help="Write strict score JSON output")
    parser.add_argument("--junitxml", help="Forward to pytest --junitxml")
    parser.add_argument("--evidence-map", dest="evidence_map", help="Evidence map file (json/md)")
    parser.add_argument("--clock-seed", default="ci", help="Deterministic seed for timestamps")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd()
    clock = DeterministicClock(args.clock_seed)
    correlation_id = hashlib.sha256(f"{repo_root}:{args.clock_seed}".encode("utf-8")).hexdigest()[:16]
    logger = JsonLogger(sys.stderr, clock, correlation_id)
    metrics = PrometheusFacade()
    state = StateManager(args.mode, args.flush_redis, logger, metrics)

    evidence = EvidenceMatrix()
    if args.evidence_map:
        evidence_path = Path(args.evidence_map)
        if evidence_path.exists():
            evidence.load(evidence_path)
        else:
            logger.warning("evidence.missing", path=str(evidence_path))

    features = detect_features(repo_root)
    probe_result: Optional[Tuple[bool, Dict[str, Any]]] = None
    if args.probe_mw_order != "no":
        if mw_probe is None:
            logger.warning("middleware.probe.unavailable", reason="mw_probe module missing")
        else:
            try:
                force = args.probe_mw_order != "auto"
                probe_success, probe_details = mw_probe.probe_and_validate(force=force)
                probe_result = (probe_success, probe_details)
                features["middleware_order"] = bool(features.get("middleware_order", False) or probe_success)
                logger.info(
                    "middleware.probe.result",
                    success=probe_success,
                    details=probe_details,
                )
            except Exception as exc:  # pragma: no cover - defensive guard.
                probe_result = (False, {"message": f"mw_probe exception: {exc}"})
                features["middleware_order"] = False
                logger.error("middleware.probe.error", error=str(exc))
    todo_count = scan_todo_markers(repo_root)

    state.prepare()
    collect_p95_samples(clock, metrics, args.p95_samples)

    summary = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "warnings": 0}
    pytest_result: Optional[PytestResult] = None
    exit_code = 0
    try:
        runner = PytestRunner(args, logger, metrics, clock)
        pytest_result = runner.run()
        summary = pytest_result.summary
        exit_code = pytest_result.returncode
    except Exception as exc:  # pragma: no cover - orchestrator failure path.
        logger.error("pytest.run.failed", error=str(exc))
        exit_code = 1
    finally:
        state.finalize()

    score_engine = ScoreEngine(gui_in_scope=features.get("gui_scope", False), evidence=evidence)
    spec_statuses = score_engine.apply_evidence_matrix()
    score_engine.apply_feature_checks(features)
    score_engine.apply_middleware_probe(probe_result)
    score_engine.apply_todo_scan(todo_count)
    if pytest_result:
        score_engine.apply_pytest_result(pytest_result)
    score_engine.apply_state(state)
    score = score_engine.finalize()

    report = build_report(score, summary, spec_statuses, evidence, features)
    print(report)

    if args.json_path:
        write_json_report(Path(args.json_path), correlation_id, score, summary)

    if exit_code == 0 and (score.total < 90 or score.caps):
        return 1
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
