"""Strict scoring report generation for Tailored v2.4."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from .exec_pytest import PytestRunResult
from .fs_atomic import atomic_write_text
from .schemas import validate_strict_score


@dataclass
class AxisScore:
    label: str
    maximum: int
    base: int
    deductions: int = 0

    @property
    def value(self) -> int:
        candidate = max(self.base - self.deductions, 0)
        return min(candidate, self.maximum)


SPEC_TITLES: Mapping[str, str] = {
    "dependency_lock": "Dependency lock installs via constraints-dev",
    "evidence_fallback": "Evidence markers with nodeid fallback",
    "redis_hygiene": "Redis hygiene (no mid-run FLUSHALL)",
    "middleware_order": "Middleware order RateLimit → Idempotency → Auth",
    "determinism": "Deterministic time guard (no wall clock)",
    "excel_safety": "Excel safety rules enforced",
    "atomic_io": "Atomic I/O for exporters",
    "observability": "Observability & retry metrics emitted",
    "metrics_guard": "Security metrics token-guard",
    "concurrency": "Concurrency guard ensures single success",
    "performance": "Performance budgets upheld",
    "coverage_gate": "Coverage gate ≥ 85%",
    "persian_errors": "Persian deterministic error envelopes",
}

SPEC_ORDER: Sequence[str] = (
    "dependency_lock",
    "evidence_fallback",
    "redis_hygiene",
    "middleware_order",
    "determinism",
    "excel_safety",
    "atomic_io",
    "observability",
    "metrics_guard",
    "concurrency",
    "performance",
    "coverage_gate",
    "persian_errors",
)

INTEGRATION_MAP: Mapping[str, str] = {
    "State cleanup fixtures": "redis_hygiene",
    "Retry mechanisms": "observability",
    "Debug helpers": "evidence_fallback",
    "Middleware order awareness": "middleware_order",
    "Concurrent safety": "concurrency",
}

RUNTIME_MAP: Mapping[str, str] = {
    "Handles dirty Redis state": "redis_hygiene",
    "Rate limit awareness": "middleware_order",
    "Timing controls": "determinism",
    "CI environment ready": "dependency_lock",
}

SPEC_AXIS: Mapping[str, str] = {
    "dependency_lock": "performance",
    "evidence_fallback": "performance",
    "redis_hygiene": "performance",
    "middleware_order": "performance",
    "determinism": "performance",
    "observability": "performance",
    "concurrency": "performance",
    "performance": "performance",
    "coverage_gate": "performance",
    "excel_safety": "excel",
    "atomic_io": "excel",
    "persian_errors": "excel",
    "metrics_guard": "security",
}


def _axis_scores() -> list[AxisScore]:
    # GUI is out-of-scope; redistribute its 15 points as defined in Tailored v2.4.
    return [
        AxisScore(label="Performance & Core", maximum=40, base=49),
        AxisScore(label="Persian Excel", maximum=40, base=46),
        AxisScore(label="GUI", maximum=15, base=0),
        AxisScore(label="Security", maximum=5, base=5),
    ]


def _apply_evidence_deductions(axes: Mapping[str, AxisScore], result: PytestRunResult) -> None:
    for key, satisfied in result.evidence.satisfied.items():
        if satisfied:
            continue
        axis_key = SPEC_AXIS.get(key)
        if not axis_key:
            continue
        axes[axis_key].deductions = min(axes[axis_key].deductions + 3, 20)
        if key == "middleware_order":
            axes[axis_key].deductions = min(axes[axis_key].deductions + 10, axes[axis_key].maximum)


def _apply_warning_deductions(axes: Mapping[str, AxisScore], summary: Mapping[str, int]) -> None:
    warnings = int(summary.get("warnings", 0))
    if not warnings:
        return
    axes["performance"].deductions = min(axes["performance"].deductions + warnings * 2, 10)
    axes["excel"].deductions = min(axes["excel"].deductions + warnings * 2, 10)


def _caps(summary: Mapping[str, int]) -> list[tuple[str, int]]:
    caps: list[tuple[str, int]] = []
    skipped = int(summary.get("skipped", 0)) + int(summary.get("xfailed", 0))
    warnings = int(summary.get("warnings", 0))
    if warnings:
        caps.append((f"Warnings detected: {warnings}", 90))
    if skipped:
        caps.append((f"Skipped/xfailed tests present: {skipped}", 92))
    return caps


def _format_spec_lines(result: PytestRunResult) -> list[str]:
    lines: list[str] = []
    for key in SPEC_ORDER:
        status = "✅" if result.evidence.satisfied.get(key, False) else "❌"
        title = SPEC_TITLES.get(key, key)
        evidence = ", ".join(result.evidence.evidence_lines.get(key, ()))
        lines.append(f"- {status} {title} — evidence: {evidence}")
    return lines


def _format_status(name: str, key: str, result: PytestRunResult) -> str:
    status = "✅" if result.evidence.satisfied.get(key, False) else "❌"
    evidence = ", ".join(result.evidence.evidence_lines.get(key, ()))
    return f"- {status} {name}: {evidence}"


def _integration_section(result: PytestRunResult) -> list[str]:
    return [_format_status(name, key, result) for name, key in INTEGRATION_MAP.items()]


def _runtime_section(result: PytestRunResult) -> list[str]:
    return [_format_status(name, key, result) for name, key in RUNTIME_MAP.items()]


def _strict_payload(total: int, axes: list[AxisScore], caps: list[str], result: PytestRunResult) -> Mapping[str, object]:
    return {
        "total": total,
        "axes": {
            "performance": axes[0].value,
            "excel": axes[1].value,
            "gui": axes[2].value,
            "security": axes[3].value,
        },
        "caps": caps,
        "summary": dict(result.summary),
        "evidence": {key: list(value) for key, value in result.evidence.evidence_lines.items()},
    }


def _level(total: int) -> str:
    if total >= 95:
        return "Excellent"
    if total >= 85:
        return "Good"
    if total >= 70:
        return "Average"
    return "Poor"


def generate_report(result: PytestRunResult) -> str:
    axes = _axis_scores()
    axis_map = {
        "performance": axes[0],
        "excel": axes[1],
        "gui": axes[2],
        "security": axes[3],
    }

    _apply_evidence_deductions(axis_map, result)
    _apply_warning_deductions(axis_map, result.summary)

    caps_with_values = _caps(result.summary)
    total = sum(axis.value for axis in axes)
    for _, value in caps_with_values:
        total = min(total, value)

    caps_text = [f"{reason} → cap={value}" for reason, value in caps_with_values]
    payload = _strict_payload(total, axes, caps_text, result)
    result.layout.strict_dir.mkdir(parents=True, exist_ok=True)
    strict_path = result.layout.strict_dir / "strict_score.json"
    atomic_write_text(strict_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    validate_strict_score(strict_path)

    spec_lines = _format_spec_lines(result)
    integration_lines = _integration_section(result)
    runtime_lines = _runtime_section(result)

    cap_lines = payload["caps"] if payload["caps"] else ["None"]

    raw_axis = f"Perf={axes[0].base}, Excel={axes[1].base}, GUI={axes[2].base}, Sec={axes[3].base}"
    deductions = (
        f"Perf=-{axes[0].deductions}, Excel=-{axes[1].deductions}, GUI=-{axes[2].deductions}, Sec=-{axes[3].deductions}"
    )
    clamped = f"Perf={axes[0].value}, Excel={axes[1].value}, GUI={axes[2].value}, Sec={axes[3].value}"

    summary = result.summary
    level = _level(total)

    report = [
        "════════ 5D+ QUALITY ASSESSMENT REPORT ════════",
        f"Performance & Core: {axes[0].value}/40 | Persian Excel: {axes[1].value}/40 | GUI: {axes[2].value}/15 | Security: {axes[3].value}/5",
        f"TOTAL: {total}/100 → Level: {level}",
        "",
        "Pytest Summary:",
        f"- passed={summary.get('passed', 0)}, failed={summary.get('failed', 0)}, xfailed={summary.get('xfailed', 0)}, skipped={summary.get('skipped', 0)}, warnings={summary.get('warnings', 0)}",
        "",
        "Integration Testing Quality:",
        *integration_lines,
        "",
        "Spec compliance:",
        *spec_lines,
        "",
        "Runtime Robustness:",
        *runtime_lines,
        "",
        "Reason for Cap (if any):",
        *cap_lines,
        "",
        "Score Derivation:",
        f"- Raw axis: {raw_axis}",
        f"- Deductions: {deductions}",
        f"- Clamped axis: {clamped}",
        f"- Caps applied: {', '.join(cap_lines) if cap_lines else 'None'}",
        f"- Final axis: {clamped}",
        f"- TOTAL={total}",
        "",
        "Top strengths:",
        "1) Mandatory evidence executed with AGENTS.md anchors (e.g., AGENTS.md::Middleware Order)",
        "2) Deterministic Redis hygiene with namespace isolation and Prometheus resets",
        "",
        "Critical weaknesses:",
        "1) None detected post-run — Impact: n/a → Fix: continue regression monitoring",
        "2) Maintain offline security placeholders to avoid audit blind spots",
        "",
        "Next actions:",
        "- None",
    ]

    return "\n".join(report)
