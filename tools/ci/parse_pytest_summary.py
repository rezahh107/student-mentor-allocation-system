"""Parse pytest summaries and emit Strict Scoring v2 5D+ quality reports."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

SUMMARY_PATTERN = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|errors?|xfailed|skipped|warnings?|warning)",
    re.IGNORECASE,
)

REQUIRED_SECTIONS: Tuple[str, ...] = (
    "2) Setup & Commands",
    "3) Absolute Guardrails (do/do-not)",
    "8) Testing & CI Gates",
    "10) User-Visible Errors (Persian, deterministic)",
)

AXIS_LIMITS: Dict[str, int] = {
    "Performance & Core": 40,
    "Persian Excel": 40,
    "GUI": 15,
    "Security": 5,
}


@dataclass
class Scores:
    raw: Dict[str, float]
    deductions: Dict[str, float]
    after_deductions: Dict[str, float]
    adjusted: Dict[str, float]
    clamped: Dict[str, float]
    final: Dict[str, float]
    caps_applied: List[str]
    cap_total: float
    final_sum: float
    bonus_perf: float
    bonus_excel: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Strict Scoring v2 report from pytest summary output.",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="Path to a file containing pytest summary lines. Reads stdin if omitted.",
    )
    parser.add_argument(
        "--summary-text",
        help="Direct pytest summary text. Overrides --summary-file if provided.",
    )
    parser.add_argument(
        "--agents-path",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "AGENTS.md",
        help="Path to the root AGENTS.md file for evidence validation.",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Repeatable flag for evidence strings (e.g. path::symbol).",
    )
    parser.add_argument(
        "--gui-out-of-scope",
        action="store_true",
        help="Reallocate GUI points to Performance & Core / Persian Excel.",
    )
    parser.add_argument(
        "--fail-under",
        type=int,
        default=95,
        help="Exit with status 1 if total score is below this threshold (default: 95).",
    )
    parser.add_argument(
        "--no-100-override",
        action="store_true",
        default=False,
        help="Retained for compatibility; No-100 Gate is always enforced.",
    )
    return parser.parse_args()


def load_summary_text(args: argparse.Namespace) -> str:
    if args.summary_text:
        return args.summary_text
    if args.summary_file:
        return args.summary_file.read_text(encoding="utf-8")
    return sys.stdin.read()


def extract_counts(text: str) -> Dict[str, int]:
    counts = {"passed": 0, "failed": 0, "xfailed": 0, "skipped": 0, "warnings": 0}
    for match in SUMMARY_PATTERN.finditer(text):
        label = match.group("label").lower()
        value = int(match.group("count"))
        if label.startswith("warning"):
            counts["warnings"] = value
        elif label.startswith("error"):
            counts["failed"] = max(counts["failed"], value)
        else:
            counts[label] = value
    return counts


def discover_agents_sections(path: Path) -> Dict[str, bool]:
    sections: Dict[str, bool] = {name: False for name in REQUIRED_SECTIONS}
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return sections
    for line in content.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            if name in sections:
                sections[name] = True
    return sections


def compute_scores(
    sections: Dict[str, bool],
    gui_out_of_scope: bool,
) -> Scores:
    raw = {axis: float(limit) for axis, limit in AXIS_LIMITS.items()}
    deductions = {axis: 0.0 for axis in AXIS_LIMITS}

    missing_sections = [name for name, present in sections.items() if not present]
    for _ in missing_sections:
        deductions["Performance & Core"] += 8
        deductions["Persian Excel"] += 6

    after_deductions = {
        axis: max(0.0, raw[axis] - deductions.get(axis, 0.0)) for axis in raw
    }

    adjusted = after_deductions.copy()
    bonus_perf = 0.0
    bonus_excel = 0.0
    if gui_out_of_scope:
        adjusted["GUI"] = 0.0
        bonus_perf = 9.0
        bonus_excel = 6.0

    clamped = {
        axis: max(0.0, min(value, AXIS_LIMITS[axis]))
        for axis, value in adjusted.items()
    }

    final = clamped.copy()
    final_sum = sum(final.values())
    total_with_bonus = final_sum + bonus_perf + bonus_excel

    return Scores(
        raw=raw,
        deductions=deductions,
        after_deductions=after_deductions,
        adjusted=adjusted,
        clamped=clamped,
        final=final,
        caps_applied=[],
        cap_total=total_with_bonus,
        final_sum=final_sum,
        bonus_perf=bonus_perf,
        bonus_excel=bonus_excel,
    )


def apply_caps(scores: Scores, counts: Dict[str, int]) -> Scores:
    cap_total = scores.cap_total
    caps_applied = list(scores.caps_applied)
    clamped = scores.clamped.copy()
    final = scores.final.copy()
    final_sum = scores.final_sum

    if counts["xfailed"] + counts["skipped"] + counts["warnings"] > 0:
        caps_applied.append("No-100 Gate: xfailed/skipped/warnings present")
        for axis, ceiling in (("Performance & Core", 30.0), ("Persian Excel", 30.0)):
            clamped[axis] = min(clamped.get(axis, 0.0), ceiling)
        final = clamped.copy()
        final_sum = sum(final.values())
        cap_total = min(final_sum + scores.bonus_perf + scores.bonus_excel, 99.0)
    else:
        cap_total = scores.cap_total

    return Scores(
        raw=scores.raw,
        deductions=scores.deductions,
        after_deductions=scores.after_deductions,
        adjusted=scores.adjusted,
        clamped=clamped,
        final=final,
        caps_applied=caps_applied,
        cap_total=cap_total,
        final_sum=final_sum,
        bonus_perf=scores.bonus_perf,
        bonus_excel=scores.bonus_excel,
    )


def compute_level(total: float) -> str:
    if total >= 90:
        return "Excellent"
    if total >= 75:
        return "Good"
    if total >= 60:
        return "Average"
    return "Poor"


def format_evidence_lines(
    sections: Dict[str, bool], provided: Iterable[str]
) -> List[str]:
    lines: List[str] = []
    for name, present in sections.items():
        status = "✅" if present else "❌"
        lines.append(f"- {status} AGENTS.md::{name}")
    for item in provided:
        prefix = "✅" if item else "❌"
        lines.append(f"- {prefix} {item or 'Evidence missing'}")
    if not any("AGENTS.md" in line for line in lines):
        lines.append("- ❌ AGENTS.md evidence missing")
    return lines


def print_report(
    scores: Scores,
    counts: Dict[str, int],
    sections: Dict[str, bool],
    evidence: Iterable[str],
) -> None:
    bonus_total = scores.bonus_perf + scores.bonus_excel
    total_capped = scores.cap_total
    level = compute_level(total_capped)

    print("════════ 5D+ QUALITY ASSESSMENT REPORT ════════")
    print(
        "Performance & Core: "
        f"{scores.final['Performance & Core']:.0f}/{AXIS_LIMITS['Performance & Core']}"
        " | Persian Excel: "
        f"{scores.final['Persian Excel']:.0f}/{AXIS_LIMITS['Persian Excel']}"
        " | GUI: "
        f"{scores.final['GUI']:.0f}/{AXIS_LIMITS['GUI']}"
        " | Security: "
        f"{scores.final['Security']:.0f}/{AXIS_LIMITS['Security']}"
    )
    print(f"TOTAL: {total_capped:.0f}/100 → Level: {level}")
    print()
    print("Pytest Summary:")
    print(
        f"- passed={counts['passed']}, failed={counts['failed']}, "
        f"xfailed={counts['xfailed']}, skipped={counts['skipped']}, warnings={counts['warnings']}"
    )
    print()
    print("Evidence Lines:")
    for line in format_evidence_lines(sections, evidence):
        print(line)
    print()
    print("Integration Testing Quality:")
    print("- State cleanup fixtures: ❌")
    print("- Retry mechanisms: ❌")
    print("- Debug helpers: ❌")
    print("- Middleware order awareness: ❌")
    print("- Concurrent safety: ❌")
    print()
    print("Spec compliance:")
    for name, present in sections.items():
        status = "✅" if present else "❌"
        print(f"- {status} {name} — evidence: AGENTS.md::{name}")
    print()
    print("Runtime Robustness:")
    print("- Handles dirty Redis state: ❌")
    print("- Rate limit awareness: ❌")
    print("- Timing controls: ❌")
    print("- CI environment ready: ❌")
    print()
    if scores.caps_applied:
        print("Reason for Cap (if any):")
        for item in scores.caps_applied:
            print(f"- {item}")
    else:
        print("Reason for Cap (if any):")
        print("- None")
    print()
    print("Score Derivation:")
    raw = scores.raw
    deductions = scores.deductions
    clamped = scores.clamped
    print(
        "- Raw axis: "
        f"Perf={raw['Performance & Core']:.0f}, "
        f"Excel={raw['Persian Excel']:.0f}, "
        f"GUI={raw['GUI']:.0f}, "
        f"Sec={raw['Security']:.0f}"
    )
    print(
        "- Deductions: "
        f"Perf=-{deductions['Performance & Core']:.0f}, "
        f"Excel=-{deductions['Persian Excel']:.0f}, "
        f"GUI=-{deductions['GUI']:.0f}, "
        f"Sec=-{deductions['Security']:.0f}"
    )
    print(
        "- Clamped axis: "
        f"Perf={clamped['Performance & Core']:.0f}, "
        f"Excel={clamped['Persian Excel']:.0f}, "
        f"GUI={clamped['GUI']:.0f}, "
        f"Sec={clamped['Security']:.0f}"
    )
    print(f"- Base total (axes): {scores.final_sum:.0f}")
    if bonus_total:
        print(
            "- Reallocation Bonus: +{total} (Perf +{perf}, Excel +{excel})".format(
                total=f"{bonus_total:.0f}",
                perf=f"{scores.bonus_perf:.0f}",
                excel=f"{scores.bonus_excel:.0f}",
            )
        )
    else:
        print("- Reallocation Bonus: +0 (Perf +0, Excel +0)")
    if scores.caps_applied:
        print(f"- Caps applied: {', '.join(scores.caps_applied)}")
    else:
        print("- Caps applied: None")
    print(
        "- Final axis: "
        f"Perf={scores.final['Performance & Core']:.0f}, "
        f"Excel={scores.final['Persian Excel']:.0f}, "
        f"GUI={scores.final['GUI']:.0f}, "
        f"Sec={scores.final['Security']:.0f}"
    )
    print(f"- TOTAL={total_capped:.0f}")


def main() -> None:
    args = parse_arguments()
    summary_text = load_summary_text(args)
    counts = extract_counts(summary_text)
    sections = discover_agents_sections(args.agents_path)
    scores = compute_scores(sections, args.gui_out_of_scope)
    scores = apply_caps(scores, counts)
    print_report(scores, counts, sections, args.evidence)
    exit_code = 0 if scores.cap_total >= args.fail_under else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
