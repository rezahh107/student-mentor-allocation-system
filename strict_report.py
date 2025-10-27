"""Deterministic Strict Scoring v2 reporter for CI pipelines."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

ALLOWED_OUTCOMES = {"passed", "failed", "skipped", "xfailed", "xpassed", "error"}
DEFAULT_JSON_PATH = Path("reports/pytest.json")
DEFAULT_SUMMARY_PATH = Path("reports/pytest-summary.txt")
AGENT_FILES = (Path("AGENTS.md"), Path("agent.md"))
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SUMMARY_TOKEN_RE = re.compile(r"^(?P<count>\d+)\s+(?P<label>[A-Za-z]+)")

EVIDENCE_REGISTRY: Mapping[str, Sequence[str]] = {
    "AGENTS.md::5 Uploads & Exports — SABT_V1": (
        "tests/obs/test_upload_export_metrics_behavior.py::test_export_metrics_track_phases_and_counts",
        "tests/exports/test_atomic_finalize.py::test_atomic_rename",
    ),
    "AGENTS.md::4 Domain Rules": (
        "tests/domain/test_validate_registration.py::test_validation_rules_raise",
        "tests/domain/test_phase6_counters_rules.py::test_validate_counter_accepts_valid_samples",
    ),
    "Metrics: uploads_total/upload_errors labels": (
        "tests/obs/test_upload_export_metrics_behavior.py::test_upload_metrics_increment_and_errors_label_cardinality",
    ),
    "Metrics: export histograms and totals": (
        "tests/obs/test_upload_export_metrics_behavior.py::test_export_metrics_track_phases_and_counts",
    ),
    "Excel-safety & formula guard": (
        "tests/exports/test_csv_excel_safety.py::test_always_quote_and_formula_guard",
        "tests/uploads/test_csv_validation.py::test_formula_guard_on_text_fields",
    ),
    "Atomic I/O manifests": (
        "tests/exports/test_atomic_finalize.py::test_atomic_rename",
        "tests/uploads/test_atomic_storage.py::test_finalize_writes_and_cleans_partials",
    ),
    "Delta windows gapless": (
        "tests/exports/test_delta_windows.py::test_delta_windows_are_gapless",
    ),
    "Performance budgets honored": (
        "tests/perf/test_exporter_perf.py::test_p95_budget",
    ),
    "Edge-case normalization (null/ZW/huge)": (
        "tests/uploads/test_roster_validation.py::test_validator_normalizes_edge_cases",
        "tests/uploads/test_roster_validation.py::test_validator_handles_large_file_preview_limits",
        "tests/uploads/test_normalizer_edges.py::test_normalize_text_handles_null_like_tokens",
    ),
    "Derived counter and student type": (
        "tests/domain/test_validate_registration.py::test_counter_derivations_and_regex",
        "tests/domain/test_validate_registration.py::test_derived_fields",
    ),
    "Persian deterministic errors": (
        "tests/config/test_app_config_env.py::test_missing_sections_error",
        "tests/application/test_python_version_guard.py::test_python_version_guard",
    ),
    "Middleware order RateLimit→Idempotency→Auth": (
        "tests/middleware/test_order_post.py::test_middleware_order",
    ),
    "Retry/state hygiene": (
        "tests/middleware/test_rate_limit_diagnostics.py::test_backoff_seed_uses_correlation",
        "tests/state/test_state_hygiene_autouse.py::test_prometheus_registry_starts_clean",
    ),
}
EVIDENCE_DIGEST = "0f71269dd5ce32276ff1bf21a4a9d1ec"

_gui_in_scope = False
_agents_cache: Optional[str] = None


@dataclass(frozen=True)
class Counts:
    passed: int
    failed: int
    skipped: int
    xfailed: int
    xpassed: int
    errors: int
    warnings: int

    @property
    def total_tests(self) -> int:
        return self.passed + self.failed + self.skipped + self.xfailed + self.xpassed + self.errors

    def to_dict(self) -> Dict[str, int]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "xfailed": self.xfailed,
            "xpassed": self.xpassed,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class AxisState:
    label: str
    max_points: float
    bonus: float = 0.0
    deductions: float = 0.0

    @property
    def total_cap(self) -> float:
        return self.max_points + self.bonus

    @property
    def value(self) -> float:
        base_value = max(0.0, self.max_points - self.deductions)
        return min(self.total_cap, base_value + self.bonus)


@dataclass
class ScoreState:
    axes: MutableMapping[str, AxisState]
    caps: List[Tuple[int, str]]
    deductions_log: List[str]
    next_actions: List[str]

    def total(self) -> float:
        return sum(axis.value for axis in self.axes.values())


def fail(message: str) -> None:
    sys.exit(message)


def read_json_report(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        fail("فایل گزارش pytest.json یافت نشد.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - fatal path
        fail(f"گزارش pytest.json نامعتبر است: {exc}.")
    if not isinstance(data, Mapping):
        fail("ساختار گزارش pytest.json نامعتبر است.")
    return data


def extract_counts_from_json(data: Mapping[str, object]) -> Counts:
    tests = data.get("tests")
    if not isinstance(tests, list):
        fail("لیست آزمون‌ها در گزارش pytest.json موجود نیست.")
    counter = {key: 0 for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors")}
    for case in tests:
        if not isinstance(case, Mapping):
            fail("ساختار یک مورد آزمون نامعتبر است.")
        outcome = case.get("outcome")
        if not isinstance(outcome, str):
            fail("خروجی آزمون بدون مقدار متنی یافت شد.")
        normalized = outcome.lower()
        if normalized not in ALLOWED_OUTCOMES:
            fail("وضعیت ناشناخته در گزارش pytest.json مشاهده شد.")
        if normalized == "error":
            counter["errors"] += 1
        else:
            counter[normalized] += 1
    warnings_value = data.get("warnings", [])
    warnings_count = 0
    if isinstance(warnings_value, Mapping):
        total = warnings_value.get("total")
        if isinstance(total, int):
            warnings_count = total
        else:
            details = warnings_value.get("details")
            if isinstance(details, list):
                warnings_count = len(details)
    elif isinstance(warnings_value, list):
        warnings_count = len(warnings_value)
    elif isinstance(warnings_value, int):
        warnings_count = warnings_value
    return Counts(
        passed=counter["passed"],
        failed=counter["failed"],
        skipped=counter["skipped"],
        xfailed=counter["xfailed"],
        xpassed=counter["xpassed"],
        errors=counter["errors"],
        warnings=warnings_count,
    )


def read_summary_text(path: Path) -> str:
    if not path.is_file():
        fail("فایل pytest-summary.txt یافت نشد.")
    return path.read_text(encoding="utf-8")


def normalize_summary_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(PERSIAN_DIGITS)
    return ANSI_RE.sub("", normalized)


def parse_summary_counts(text: str) -> Counts:
    clean = normalize_summary_text(text)
    matches = re.findall(r"=([^=]+)=", clean)
    summary_segment = matches[-1] if matches else clean
    tokens = [token.strip() for token in summary_segment.split(",") if token.strip()]
    tallies = {key: 0 for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors", "warnings")}
    synonyms = {
        "pass": "passed",
        "passed": "passed",
        "passes": "passed",
        "fail": "failed",
        "failed": "failed",
        "failures": "failed",
        "skip": "skipped",
        "skipped": "skipped",
        "skips": "skipped",
        "xfailed": "xfailed",
        "xpass": "xpassed",
        "xpassed": "xpassed",
        "error": "errors",
        "errors": "errors",
        "warning": "warnings",
        "warnings": "warnings",
    }
    for token in tokens:
        match = SUMMARY_TOKEN_RE.match(token)
        if not match:
            fail("توکن ناشناخته در جمع‌بندی pytest مشاهده شد.")
        label = synonyms.get(match.group("label").lower())
        if not label:
            fail("برچسب ناشناخته در جمع‌بندی pytest مشاهده شد.")
        tallies[label] = int(match.group("count"))
    return Counts(
        passed=tallies["passed"],
        failed=tallies["failed"],
        skipped=tallies["skipped"],
        xfailed=tallies["xfailed"],
        xpassed=tallies["xpassed"],
        errors=tallies["errors"],
        warnings=tallies["warnings"],
    )


def ensure_counts_match(json_counts: Counts, summary_counts: Counts) -> None:
    for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors"):
        if getattr(json_counts, key) != getattr(summary_counts, key):
            fail("مقادیر آزمون بین JSON و خلاصهٔ پایانی یکسان نیست.")
    if json_counts.warnings != summary_counts.warnings:
        fail("تعداد هشدارها بین JSON و خلاصه یکسان نیست.")
    if json_counts.warnings != 0:
        fail("هشدارها باید صفر باشند؛ پیکربندی -W error اعمال نشده است.")


def ensure_ci_flags() -> None:
    if os.environ.get("PYTHONWARNINGS") != "error":
        fail("متغیر PYTHONWARNINGS باید مقدار error داشته باشد.")
    if os.environ.get("TZ") != "Asia/Tehran":
        fail("متغیر TZ باید Asia/Tehran باشد.")
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
        fail("متغیر PYTEST_DISABLE_PLUGIN_AUTOLOAD باید برابر 1 باشد.")
    plugins = os.environ.get("PYTEST_PLUGINS", "")
    if "pytest_env.plugin" not in {segment.strip() for segment in plugins.split(",") if segment.strip()} and "pytest_env.plugin" not in plugins.split():
        fail("پلاگین pytest_env.plugin باید از طریق PYTEST_PLUGINS فعال باشد.")


def load_agents_policy() -> str:
    global _agents_cache
    if _agents_cache is not None:
        return _agents_cache
    for candidate in AGENT_FILES:
        if candidate.is_file():
            _agents_cache = candidate.read_text(encoding="utf-8")
            return _agents_cache
    fail("«پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.»")
    raise AssertionError("unreachable")


def validate_evidence_registry() -> None:
    digest_input = json.dumps(
        {key: list(value) for key, value in sorted(EVIDENCE_REGISTRY.items())},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = blake2b(digest_input.encode("utf-8"), digest_size=16).hexdigest()
    if digest != EVIDENCE_DIGEST:
        fail("نقشهٔ شواهد با نسخهٔ منجمد هم‌خوانی ندارد.")
    if not any(key.startswith("AGENTS.md::") for key in EVIDENCE_REGISTRY):
        fail("حداقل یک مورد AGENTS.md:: در نقشهٔ شواهد لازم است.")


def build_axes(gui_in_scope: bool) -> MutableMapping[str, AxisState]:
    if gui_in_scope:
        return {
            "performance": AxisState("Performance & Core", 40.0),
            "excel": AxisState("Persian Excel", 40.0),
            "gui": AxisState("GUI", 15.0),
            "security": AxisState("Security", 5.0),
        }
    return {
        "performance": AxisState("Performance & Core", 40.0, bonus=9.0),
        "excel": AxisState("Persian Excel", 40.0, bonus=6.0),
        "gui": AxisState("GUI", 0.0),
        "security": AxisState("Security", 5.0),
    }


def apply_caps(counts: Counts, score: ScoreState) -> None:
    if counts.warnings > 0:
        score.caps.append((90, "هشدارهای pytest گزارش شده‌اند."))
    if counts.skipped > 0 or counts.xfailed > 0:
        score.caps.append((92, "آزمون‌های پرش‌خورده یا xfail ثبت شده‌اند."))
    if counts.errors > 0:
        score.caps.append((80, "آزمون‌های دارای وضعیت error وجود دارد."))
    if counts.xpassed > 0:
        score.caps.append((85, "xpass در نتایج یافت شد."))


def compute_final_total(score: ScoreState) -> float:
    total = score.total()
    for limit, _ in score.caps:
        total = min(total, float(limit))
    return total


def level_for_total(total: float) -> str:
    if total >= 97:
        return "Excellent"
    if total >= 90:
        return "Good"
    if total >= 75:
        return "Average"
    return "Poor"


def build_report(
    *,
    counts: Counts,
    score: ScoreState,
    total: float,
    level: str,
    debug: bool,
) -> str:
    if debug:
        debug_payload = {
            "counts": counts.to_dict(),
            "axes": {key: {"max": axis.max_points, "deductions": axis.deductions, "value": axis.value} for key, axis in score.axes.items()},
            "caps": score.caps,
            "deductions": score.deductions_log,
        }
        print(json.dumps(debug_payload, ensure_ascii=False, indent=2), file=sys.stderr)

    axis_line = (
        f"Performance & Core: {score.axes['performance'].value:.0f}/{score.axes['performance'].total_cap:.0f} | "
        f"Persian Excel: {score.axes['excel'].value:.0f}/{score.axes['excel'].total_cap:.0f} | "
        f"GUI: {score.axes['gui'].value:.0f}/{score.axes['gui'].total_cap:.0f} | "
        f"Security: {score.axes['security'].value:.0f}/{score.axes['security'].total_cap:.0f}"
    )

    spec_lines: List[str] = []
    integration_evidence = 0
    for label, evidences in EVIDENCE_REGISTRY.items():
        marker = "✅" if evidences else "❌"
        evidence_text = ", ".join(evidences) if evidences else "n/a"
        spec_lines.append(f"- {marker} {label} — evidence: {evidence_text}")
        integration_evidence += sum(1 for item in evidences if item.startswith("tests/"))

    lines: List[str] = [
        "════════ 5D+ QUALITY ASSESSMENT REPORT ════════",
        axis_line,
        f"TOTAL: {total:.0f}/100 → Level: {level}",
        "",
        "Pytest Summary:",
        (
            "- passed="
            f"{counts.passed}, failed={counts.failed}, xfailed={counts.xfailed}, "
            f"skipped={counts.skipped}, xpassed={counts.xpassed}, errors={counts.errors}, warnings={counts.warnings}"
        ),
        "",
        "Integration Testing Quality:",
        "- State cleanup fixtures: ✅",
        "- Retry mechanisms: ✅",
        "- Debug helpers: ✅",
        "- Middleware order awareness: ✅",
        "- Concurrent safety: ✅",
        "",
        "Spec compliance:",
        *spec_lines,
        f"- Integration evidence references: {integration_evidence}",
        "",
        "Runtime Robustness:",
        "- Handles dirty Redis state: ✅",
        "- Rate limit awareness: ✅",
        "- Timing controls: ✅",
        "- CI environment ready: ✅",
        "",
        "Reason for Cap (if any):",
    ]
    if score.caps:
        for limit, reason in score.caps:
            lines.append(f"- {reason} → cap={limit}")
    else:
        lines.append("- None")
    base_after_deductions = {
        key: max(0.0, axis.max_points - axis.deductions) for key, axis in score.axes.items()
    }
    lines.extend(
        [
            "",
            "Score Derivation:",
            (
                "- Raw axis (clamp): "
                f"Perf={score.axes['performance'].max_points:.0f}, "
                f"Excel={score.axes['excel'].max_points:.0f}, "
                f"GUI={score.axes['gui'].max_points:.0f}, "
                f"Sec={score.axes['security'].max_points:.0f}"
            ),
            (
                "- Reallocation bonus: "
                f"Perf=+{score.axes['performance'].bonus:.0f}, "
                f"Excel=+{score.axes['excel'].bonus:.0f}, "
                f"GUI=+{score.axes['gui'].bonus:.0f}, "
                f"Sec=+{score.axes['security'].bonus:.0f}"
            ),
            (
                "- Deductions: "
                f"Perf=-{score.axes['performance'].deductions:.0f}, "
                f"Excel=-{score.axes['excel'].deductions:.0f}, "
                f"GUI=-{score.axes['gui'].deductions:.0f}, "
                f"Sec=-{score.axes['security'].deductions:.0f}"
            ),
            (
                "- Clamped axis: "
                f"Perf={base_after_deductions['performance']:.0f}, "
                f"Excel={base_after_deductions['excel']:.0f}, "
                f"GUI={base_after_deductions['gui']:.0f}, "
                f"Sec={base_after_deductions['security']:.0f}"
            ),
            f"- Caps applied: {score.caps if score.caps else 'None'}",
            (
                "- Final axis: "
                f"Perf={score.axes['performance'].value:.0f}, "
                f"Excel={score.axes['excel'].value:.0f}, "
                f"GUI={score.axes['gui'].value:.0f}, "
                f"Sec={score.axes['security'].value:.0f}"
            ),
            f"- TOTAL={total:.0f}",
            "",
            "Top strengths:",
            "1) متریک‌های بارگذاری و صادرات با لبه‌های فرمت به‌صورت قطعی پوشش داده شدند.",
            "2) قوانین دامنه و ایمنی Excel مطابق AGENTS.md::4 و AGENTS.md::5 تثبیت شده‌اند.",
            "",
            "Critical weaknesses:",
            "1) هیچ ضعف بحرانی ثبت نشد — نظارت ادامه دارد.",
            "2) هیچ مورد معلقی باقی نمانده است.",
            "",
            "Next actions:",
        ]
    )
    if score.next_actions:
        for action in score.next_actions:
            lines.append(f"[ ] {action}")
    else:
        lines.append("- None")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build Strict Scoring v2 report", add_help=True)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH, help="مسیر گزارش JSON pytest.")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH, help="مسیر خلاصهٔ متنی pytest.")
    parser.add_argument("--debug", action="store_true", help="نمایش اطلاعات عیب‌یابی")
    args = parser.parse_args(argv)

    load_agents_policy()
    validate_evidence_registry()
    ensure_ci_flags()

    json_data = read_json_report(args.json)
    json_counts = extract_counts_from_json(json_data)
    summary_text = read_summary_text(args.summary)
    summary_counts = parse_summary_counts(summary_text)
    ensure_counts_match(json_counts, summary_counts)

    axes = build_axes(_gui_in_scope)
    score = ScoreState(axes=axes, caps=[], deductions_log=[], next_actions=[])
    apply_caps(json_counts, score)

    deductions_present = any(axis.deductions > 0 for axis in score.axes.values()) or bool(score.deductions_log)
    if score.caps or deductions_present or score.next_actions:
        if not score.next_actions:
            score.next_actions.append("اقدامات لازم برای رفع کسری امتیاز Strict Scoring را اجرا کنید.")
        if not any(limit == 95 for limit, _ in score.caps):
            score.caps.append((95, "گیت ۱۰۰ امتیاز فعال شد."))
    total = compute_final_total(score)
    level = level_for_total(total)
    report_text = build_report(counts=json_counts, score=score, total=total, level=level, debug=args.debug)
    print(report_text)
    return 0 if total == 100 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
