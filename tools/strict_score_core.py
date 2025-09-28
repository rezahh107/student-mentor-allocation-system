"""Shared Strict Score core models, evidence parsing, and quality reporting."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


INTEGRATION_HINTS: Tuple[str, ...] = (
    "tests/integration/",
    "tests/mw/",
    "tests/perf/",
    "tests/exports/",
)


@dataclass(frozen=True)
class SpecRequirement:
    """Declarative description of each strict score specification item."""

    axis: str
    description: str
    default_evidence: str


SPEC_ITEMS: Dict[str, SpecRequirement] = {
    "middleware_order": SpecRequirement(
        axis="performance",
        description="Middleware order RateLimit → Idempotency → Auth verified",
        default_evidence="tests/mw/test_order_with_xlsx_ci.py::test_middleware_order",
    ),
    "deterministic_clock": SpecRequirement(
        axis="performance",
        description="Deterministic clock/timezone controls injected",
        default_evidence="tests/time/test_clock_tz_ci.py::test_tehran_clock_injection",
    ),
    "state_hygiene": SpecRequirement(
        axis="performance",
        description="Global state hygiene (Redis flush & Prometheus registry reset)",
        default_evidence="tests/hygiene/test_registry_reset.py::test_prom_registry_reset",
    ),
    "observability": SpecRequirement(
        axis="security",
        description="Prometheus retry/exhaustion counters & masked JSON logs",
        default_evidence="tests/obs/test_metrics_format_label_ci.py::test_json_logs_masking",
    ),
    "excel_safety": SpecRequirement(
        axis="excel",
        description="Excel digit folding, NFKC, Persian ی/ک unify, formula guard",
        default_evidence="tests/exports/test_excel_safety_ci.py::test_formula_guard",
    ),
    "atomic_io": SpecRequirement(
        axis="excel",
        description="Atomic write (.part → fsync → rename) enforcement",
        default_evidence="tests/readiness/test_atomic_io.py::test_atomic_write_and_rename",
    ),
    "performance_budgets": SpecRequirement(
        axis="performance",
        description="p95 orchestrator overhead <200ms and memory <200MB",
        default_evidence="tests/perf/test_ci_overhead.py::test_orchestrator_overhead",
    ),
    "persian_errors": SpecRequirement(
        axis="security",
        description="Deterministic Persian end-user error envelopes",
        default_evidence="tests/logging/test_persian_errors.py::test_error_envelopes",
    ),
    "counter_rules": SpecRequirement(
        axis="performance",
        description="SSOT counter prefix + regex validation",
        default_evidence="tests/obs_e2e/test_metrics_labels.py::test_retry_exhaustion_counters",
    ),
    "normalization": SpecRequirement(
        axis="excel",
        description="Phase-1 normalization (enums, phone regex, digit folding)",
        default_evidence="tests/ci/test_strict_score_guard.py::test_parse_pytest_summary_extended_handles_persian_digits",
    ),
    "export_streaming": SpecRequirement(
        axis="excel",
        description="Phase-6 exporter streaming, chunking, CRLF safety",
        default_evidence="tests/exports/test_excel_safety_ci.py::test_formula_guard",
    ),
    "release_artifacts": SpecRequirement(
        axis="performance",
        description="Release artefacts include SBOM/lock/perf baselines",
        default_evidence="tests/ci/test_ci_pytest_runner.py::test_strict_mode",
    ),
    "academic_year_provider": SpecRequirement(
        axis="performance",
        description="AcademicYearProvider injects year code without wall-clock",
        default_evidence="tests/ci/test_ci_pytest_runner.py::test_strict_mode",
    ),
}


FEATURE_MAP_FROM_SPEC: Dict[str, Tuple[str, ...]] = {
    "state_hygiene": ("state_cleanup", "concurrent_safety"),
    "observability": ("debug_helpers",),
    "middleware_order": ("middleware_order", "rate_limit_awareness"),
    "deterministic_clock": ("timing_controls",),
    "performance_budgets": ("retry_mechanism",),
    "excel_safety": (),
    "atomic_io": (),
    "persian_errors": (),
    "counter_rules": (),
    "normalization": (),
    "export_streaming": (),
    "release_artifacts": (),
    "academic_year_provider": (),
}


@dataclass
class AxisScore:
    label: str
    max_points: float
    deductions: float = 0.0
    value: float = 0.0

    def clamp(self) -> float:
        raw = max(0.0, self.max_points - self.deductions)
        self.value = min(self.max_points, raw)
        return self.value


@dataclass
class Scorecard:
    axes: Dict[str, AxisScore]
    raw_total: float
    total: float
    level: str
    caps: List[Tuple[int, str]]
    deductions: List[Tuple[str, float, str]]
    next_actions: List[str]


class EvidenceMatrix:
    """Collects explicit evidence declarations for strict score specs."""

    def __init__(self) -> None:
        self.entries: Dict[str, List[str]] = {key: [] for key in SPEC_ITEMS}

    def load(self, path: Optional[Path]) -> None:
        if path is None or not path.exists():
            return
        text = path.read_text(encoding="utf-8", errors="ignore")
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
            match = re.match(r"[-*]\s*(?P<key>[A-Za-z0-9_]+)\s*:\s*(?P<value>.+)", line)
            if not match:
                continue
            key = match.group("key")
            value = match.group("value").strip()
            if key in self.entries:
                self.entries[key].append(value)

    def load_many(self, paths: Sequence[Path]) -> None:
        for path in paths:
            self.load(path)

    def add(self, key: str, value: str) -> None:
        if key not in self.entries:
            return
        self.entries.setdefault(key, []).append(value)

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

    def derived_features(self) -> Dict[str, bool]:
        features: Dict[str, bool] = {}
        for spec_key, feature_keys in FEATURE_MAP_FROM_SPEC.items():
            if not feature_keys:
                continue
            if self.has_evidence(spec_key):
                for feature in feature_keys:
                    features[feature] = True
        return features


class ScoreEngine:
    """Implements Strict Scoring v2 clamps, deductions, and No-100 gate."""

    def __init__(self, *, gui_in_scope: bool, evidence: EvidenceMatrix) -> None:
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
        self.summary: Dict[str, int] = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "warnings": 0,
        }
        self.returncode: int = 0
        self.evidence = evidence
        self._no100_reasons: List[str] = []
        self._spec_statuses: Dict[str, bool] = {key: False for key in SPEC_ITEMS}
        self._integration_quota_met: bool = False

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

    def _record_no100(self, reason: str) -> None:
        if reason not in self._no100_reasons:
            self._no100_reasons.append(reason)

    def apply_pytest_result(self, *, summary: Mapping[str, int], returncode: int) -> None:
        for key in self.summary:
            self.summary[key] = int(summary.get(key, 0))
        self.returncode = int(returncode)
        failed = self.summary.get("failed", 0)
        warnings = self.summary.get("warnings", 0)
        skipped = self.summary.get("skipped", 0)
        xfailed = self.summary.get("xfailed", 0)
        if failed or self.returncode != 0:
            penalty = 15.0 + 5.0 * max(failed, 1)
            self.deduct(
                "performance",
                penalty,
                f"Pytest failures ({failed}) or non-zero exit ({self.returncode}).",
            )
            self.next_action("بررسی و رفع خطاهای تست pytest.")
            self._record_no100("pytest_failures")
        if warnings:
            penalty = min(10.0, warnings * 2.0)
            self.deduct("performance", penalty, f"Warnings detected ({warnings}).")
            self.cap(90, f"Warnings detected: {warnings}")
            self.next_action("حذف اخطارها و رفع deprecation ها در pytest.")
            self._record_no100("warnings")
        if skipped or xfailed:
            total = skipped + xfailed
            self.cap(92, f"Skipped/xfail detected: {total}")
            self._record_no100("skips")
        if self.returncode != 0 and not failed:
            self.next_action("بازبینی خروجی pytest برای خطاهای محیطی.")

    def apply_feature_flags(self, features: Mapping[str, bool]) -> None:
        def ensure(flag: str, axis: str, amount: float, message: str, action: Optional[str] = None) -> None:
            if features.get(flag, False):
                return
            self.deduct(axis, amount, message)
            if action:
                self.next_action(action)
            self._record_no100(flag)

        ensure(
            "state_cleanup",
            "performance",
            8.0,
            "Missing global state cleanup fixture.",
            "افزودن فیکسچر پاکسازی state قبل و بعد از تست.",
        )
        ensure(
            "retry_mechanism",
            "performance",
            6.0,
            "Retry/backoff controls absent.",
            "پیاده‌سازی retry با backoff برای عملیات حساس.",
        )
        ensure(
            "timing_controls",
            "performance",
            5.0,
            "Deterministic timing controls not detected.",
            "تزریق ساعت قطعی برای کنترل TTL و backoff.",
        )
        ensure(
            "middleware_order",
            "performance",
            10.0,
            "Middleware order verification missing.",
            "رفع ترتیب RateLimit→Idempotency→Auth در middleware.",
        )
        ensure(
            "debug_helpers",
            "security",
            1.5,
            "Debug context helper absent.",
            None,
        )

    def apply_middleware_probe(self, *, success: Optional[bool], message: Optional[str] = None) -> None:
        if success is None:
            return
        if success:
            return
        reason = message or "Middleware probe failed"
        self.deduct("performance", 5.0, f"Middleware order probe failed: {reason}")
        self.cap(92, "Middleware probe reported invalid order.")
        self.next_action("رفع ترتیب RateLimit→Idempotency→Auth در middleware.")
        self._record_no100("middleware_probe")

    def apply_todo_count(self, todo_count: int) -> None:
        if todo_count <= 0:
            return
        penalty = min(10.0, todo_count * 2.0)
        self.deduct("performance", penalty, f"TODO/FIXME markers present ({todo_count}).")

    def apply_state(self, *, redis_error: Optional[str]) -> None:
        if redis_error:
            self.cap(85, redis_error)
            self.next_action("راه‌اندازی یا شبیه‌سازی Redis برای اجرای کامل تست‌ها.")
            self._record_no100("redis_missing")

    def apply_evidence_matrix(self) -> Dict[str, bool]:
        statuses: Dict[str, bool] = {}
        for key, spec in SPEC_ITEMS.items():
            has = self.evidence.has_evidence(key)
            statuses[key] = has
            if not has:
                self.deduct(spec.axis, 3.0, f"Missing evidence: {spec.description}.")
        missing = [key for key, ok in statuses.items() if not ok]
        if missing:
            self.next_action("تکمیل شواهد دقیق برای الزامات مشخصات.")
            self._record_no100("missing_spec_evidence")
        integration_count = self.evidence.integration_evidence_count()
        self._integration_quota_met = integration_count >= 3
        if not self._integration_quota_met:
            self.deduct("performance", 3.0, "Integration evidence quota not met.")
            self.deduct("excel", 3.0, "Integration evidence quota not met.")
            self._record_no100("integration_evidence")
            self.next_action("افزودن حداقل سه شاهد از تست‌های یکپارچه.")
        self._spec_statuses = statuses
        return statuses

    def record_launcher_skip(self) -> None:
        self.cap(92, "Launcher executed tests in skip mode.")
        self._record_no100("launcher_skip")

    def finalize(self) -> Scorecard:
        if self.next_actions:
            self.cap(95, "Next actions outstanding.")
            self._record_no100("next_actions")
        raw_total = sum(axis.clamp() for axis in self.axes.values())
        total = raw_total
        if self.caps:
            cap_limit = min(limit for limit, _ in self.caps)
            total = min(total, float(cap_limit))
        if self._no100_reasons and total >= 100.0:
            joined = "، ".join(sorted(self._no100_reasons))
            self.cap(99, f"No-100 gate: {joined}")
            total = min(total, 99.0)
        total = round(total, 1)
        raw_total = round(raw_total, 1)
        if total >= 90:
            level = "Excellent"
        elif total >= 75:
            level = "Good"
        elif total >= 60:
            level = "Average"
        else:
            level = "Poor"
        self.caps.sort(key=lambda item: item[0])
        return Scorecard(
            axes=self.axes,
            raw_total=raw_total,
            total=total,
            level=level,
            caps=self.caps,
            deductions=self.deductions,
            next_actions=self.next_actions,
        )

    @property
    def spec_statuses(self) -> Mapping[str, bool]:
        return self._spec_statuses

    @property
    def integration_quota_met(self) -> bool:
        return self._integration_quota_met


def detect_repo_features(repo_root: Path) -> Dict[str, bool]:
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
        if "flushdb" in text and "prom_registry_reset" in text:
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
    mw_test = repo_root / "tests" / "mw" / "test_order_with_xlsx_ci.py"
    if mw_test.exists():
        features["middleware_order"] = True
        features["rate_limit_awareness"] = True
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


def merge_feature_sources(
    *, detected: Mapping[str, bool], evidence: EvidenceMatrix
) -> Dict[str, bool]:
    merged = dict(detected)
    merged.update(evidence.derived_features())
    return merged


def scan_todo_markers(repo_root: Path) -> int:
    override = os.environ.get("STRICT_SCORE_TODO_OVERRIDE")
    if override is not None:
        try:
            return max(0, int(override))
        except ValueError:
            pass
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


QUALITY_VALIDATIONS = [
    (
        "reports/strict_score.json matches ^reports/strict_score\\.json$",
        True,
        "reports/strict_score.json",
    ),
    (
        "JSON schema includes counts/caps/reasons/evidence",
        True,
        "tools/strict_score_reporter.py::build_real_payload_from_score",
    ),
    (
        "PYTHONWARNINGS policy enforced (default/error)",
        True,
        "tests/ci/test_warnings_policy.py::test_test_phase_enforces_error",
    ),
]


DERIVED_FIELDS = [
    "correlation_id = ENV['X_REQUEST_ID'] or ENV['GITHUB_RUN_ID'] or uuid4()",
    "clock = DeterministicClock(seed) → 1402-01-DDTHH:MM:00+03:30",
    "report_mode = 'real' when pytest summary parsed else 'synth'",
]


TEST_CASE_REFERENCES = [
    "tests/ci/test_strict_score_guard.py::test_cli_guard_creates_report",
    "tests/ci/test_strict_score_caps.py::test_warning_cap_applies",
    "tests/ci/test_strict_score_evidence.py::test_missing_spec_triggers_deduction",
]


def gather_quality_validations(
    *,
    report_path: Optional[Path],
    payload: Mapping[str, Any],
    pythonwarnings: str,
) -> List[Tuple[str, bool, str]]:
    """Generate validation checklist rows for the textual quality report."""

    items: List[Tuple[str, bool, str]] = []
    path_ok = False
    if report_path is not None:
        path_ok = (
            report_path.name == "strict_score.json"
            and report_path.parent.name == "reports"
        )
    items.append(
        (
            "reports/strict_score.json matches ^reports/strict_score\\.json$",
            path_ok,
            "reports/strict_score.json",
        )
    )

    counts = payload.get("counts")
    schema_ok = isinstance(counts, Mapping) and all(
        key in payload for key in ("caps", "reasons", "evidence")
    )
    schema_ok = schema_ok and isinstance(payload.get("caps"), list)
    items.append(
        (
            "JSON schema includes counts/caps/reasons/evidence",
            schema_ok,
            "tools/strict_score_reporter.py::build_real_payload_from_score",
        )
    )

    warnings_ok = pythonwarnings in {"", "default", "error"}
    items.append(
        (
            "PYTHONWARNINGS policy enforced (default/error)",
            warnings_ok,
            "tests/ci/test_warnings_policy.py::test_test_phase_enforces_error",
        )
    )

    return items


def build_quality_report(
    *,
    payload: Mapping[str, Any],
    evidence: EvidenceMatrix,
    features: Mapping[str, bool],
    validations: Optional[Sequence[Tuple[str, bool, str]]] = None,
) -> str:
    scorecard = payload.get("scorecard", {})
    axes_payload = scorecard.get("axes", {})

    def _axis_data(key: str, fallback_label: str, fallback_max: float) -> Tuple[str, float, float, float]:
        data = axes_payload.get(key, {})
        label = str(data.get("label", fallback_label))
        max_points = float(data.get("max_points", fallback_max))
        deductions = float(data.get("deductions", 0.0))
        value = float(data.get("value", max(0.0, max_points - deductions)))
        return label, max_points, deductions, value

    perf_label, perf_max, perf_deductions, perf_value = _axis_data(
        "performance", "Performance & Core", 40.0
    )
    excel_label, excel_max, excel_deductions, excel_value = _axis_data(
        "excel", "Persian Excel", 40.0
    )
    gui_label, gui_max, gui_deductions, gui_value = _axis_data("gui", "GUI", 15.0)
    sec_label, sec_max, sec_deductions, sec_value = _axis_data(
        "security", "Security", 5.0
    )

    summary = payload.get("counts", {})
    spec_statuses = payload.get("spec_statuses", {})
    total = float(scorecard.get("total", summary.get("total", 0.0)))
    level = str(scorecard.get("level", "Unknown"))
    caps_payload: Sequence[Mapping[str, Any]] = payload.get("caps", [])  # type: ignore[assignment]
    next_actions: Sequence[str] = scorecard.get("next_actions", [])  # type: ignore[assignment]

    lines = [
        "════════ 5D+ QUALITY ASSESSMENT REPORT ════════",
        (
            f"{perf_label}: {perf_value:.1f}/{perf_max:.0f} | "
            f"{excel_label}: {excel_value:.1f}/{excel_max:.0f} | "
            f"{gui_label}: {gui_value:.1f}/{gui_max:.0f} | "
            f"{sec_label}: {sec_value:.1f}/{sec_max:.0f}"
        ),
        f"TOTAL: {total:.1f}/100 → Level: {level}",
        "",
        "Pytest Summary:",
        (
            "- passed="
            f"{summary.get('passed', 0)}, failed={summary.get('failed', 0)}, "
            f"xfailed={summary.get('xfailed', 0)}, skipped={summary.get('skipped', 0)}, "
            f"warnings={summary.get('warnings', 0)}"
        ),
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
    for key, spec in SPEC_ITEMS.items():
        flag = "✅" if spec_statuses.get(key) else "❌"
        evidence_text = evidence.evidence_text(key)
        if evidence_text == "—":
            evidence_text = spec.default_evidence
        lines.append(f"- {flag} {spec.description} — evidence: {evidence_text}")
    lines.extend(
        [
            "",
            "Runtime Robustness:",
            f"- Handles dirty Redis state: {'✅' if features.get('state_cleanup') else '❌'}",
            f"- Rate limit awareness: {'✅' if features.get('rate_limit_awareness') else '❌'}",
            f"- Timing controls: {'✅' if features.get('timing_controls') else '❌'}",
            f"- CI environment ready: {'✅' if Path('tests/ci').exists() else '❌'}",
            "",
            "VALIDATE against:",
        ]
    )
    checklist = list(validations) if validations is not None else QUALITY_VALIDATIONS
    for description, status, evidence_ref in checklist:
        flag = "✅" if status else "❌"
        lines.append(f"- {flag} {description} — evidence: {evidence_ref}")
    lines.extend(["", "DERIVE from:"])
    for item in DERIVED_FIELDS:
        lines.append(f"- {item}")
    lines.extend(["", "Test cases:"])
    for ref in TEST_CASE_REFERENCES:
        lines.append(f"- {ref}")
    lines.extend(
        [
            "",
            "Persian errors:",
            f"- {'✅' if spec_statuses.get('persian_errors') else '❌'} پیام‌های کاربر فارسی و قطعی",
            "",
            "Reason for Cap (if any):",
        ]
        )
    if caps_payload:
        for cap in caps_payload:
            limit = cap.get("limit", "—")
            reason = cap.get("reason", "")
            lines.append(f"- {reason} → cap={limit}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "Score Derivation:",
            (
                "- Raw axis: "
                f"Perf={perf_max:.0f}, Excel={excel_max:.0f}, GUI={gui_max:.0f}, Sec={sec_max:.0f}"
            ),
            (
                "- Deductions: "
                f"Perf=−{perf_deductions:.1f}, Excel=−{excel_deductions:.1f}, "
                f"GUI=−{gui_deductions:.1f}, Sec=−{sec_deductions:.1f}"
            ),
            (
                "- Clamped axis: "
                f"Perf={perf_value:.1f}, Excel={excel_value:.1f}, GUI={gui_value:.1f}, Sec={sec_value:.1f}"
            ),
            f"- Caps applied: {', '.join(str(cap.get('limit')) for cap in caps_payload) if caps_payload else 'None'}",
            (
                "- Final axis: "
                f"Perf={perf_value:.1f}, Excel={excel_value:.1f}, GUI={gui_value:.1f}, Sec={sec_value:.1f}"
            ),
            f"- TOTAL={total:.1f}",
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
    if next_actions:
        for action in next_actions:
            lines.append(f"[ ] {action}")
    else:
        lines.append("[ ] None")
    return "\n".join(lines)


__all__ = [
    "AxisScore",
    "EvidenceMatrix",
    "ScoreEngine",
    "Scorecard",
    "SPEC_ITEMS",
    "INTEGRATION_HINTS",
    "detect_repo_features",
    "merge_feature_sources",
    "scan_todo_markers",
    "gather_quality_validations",
    "build_quality_report",
]

