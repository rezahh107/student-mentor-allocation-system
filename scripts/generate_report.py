from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "report.json"
BENCHMARK_PATH = ROOT / "benchmark.json"
COVERAGE_PATH = ROOT / "coverage.json"
GATES_PATH = ROOT / "gates.json"
REPORTS_DIR = ROOT / "reports"
SUMMARY_PATH = REPORTS_DIR.parent / "codex_summary.json"
MARKDOWN_PATH = REPORTS_DIR / "continuous_testing_report.md"
ALERT_PATH = REPORTS_DIR / "error_alert.md"


FA_STRINGS = {
    "report_title": "\u06af\u0632\u0627\u0631\u0634 \u06a9\u06cc\u0641\u06cc\u062a \u067e\u06cc\u0648\u0633\u062a\u0647",
    "badges": "\u0646\u0634\u0627\u0646\u200c\u0647\u0627",
    "summary_heading": "\u062e\u0644\u0627\u0635\u0647",
    "summary_done": "\u0628\u0631\u0631\u0633\u06cc\u200c\u0647\u0627\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 \u06a9\u06cc\u0641\u06cc\u062a \u0627\u0646\u062c\u0627\u0645 \u0634\u062f.",
    "tests": "\u0646\u062a\u0627\u06cc\u062c \u062a\u0633\u062a",
    "actions": "\u0627\u0642\u062f\u0627\u0645\u0627\u062a",
    "selection": "\u0627\u0646\u062a\u062e\u0627\u0628 \u062a\u0633\u062a",
    "slow": "\u06a9\u0646\u062f\u062a\u0631\u06cc\u0646 \u062a\u0633\u062a\u200c\u0647\u0627",
    "skipped": "\u062a\u0633\u062a\u200c\u0647\u0627\u06cc \u0631\u062f \u0634\u062f\u0647",
    "phase": "\u062a\u0641\u06a9\u06cc\u06a9 \u0641\u0627\u0632",
    "performance": "\u0639\u0645\u0644\u06a9\u0631\u062f",
    "alert_title": "\u0647\u0634\u062f\u0627\u0631",
    "alert_intro": "\u062f\u0631 \u062c\u0631\u06cc\u0627\u0646 \u0628\u0631\u0631\u0633\u06cc\u200c\u0647\u0627\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 \u0645\u0634\u06a9\u0644 \u0634\u0646\u0627\u0633\u0627\u06cc\u06cc \u0634\u062f.",
    "reasons": "\u062f\u0644\u0627\u06cc\u0644",
    "next_steps": "\u0627\u0642\u062f\u0627\u0645\u0627\u062a \u0628\u0639\u062f\u06cc",
    "all_passed": "\u0647\u0645\u0647 \u062a\u0633\u062a\u200c\u0647\u0627 \u0628\u0627 \u0645\u0648\u0641\u0642\u06cc\u062a \u0627\u062c\u0631\u0627 \u0634\u062f\u0646\u062f.",
    "no_skipped": "\u0645\u0648\u0631\u062f\u06cc \u0628\u0631\u0627\u06cc \u06af\u0632\u0627\u0631\u0634 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f.",
    "full_suite": "\u06a9\u0644 \u0645\u062c\u0645\u0648\u0639\u0647",
    "issues_detected": "\u0645\u0634\u06a9\u0644 \u0634\u0646\u0627\u0633\u0627\u06cc\u06cc \u0634\u062f.",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return default


def classify(test: Dict[str, Any]) -> Tuple[str, str]:
    nodeid: str = test.get("nodeid", "")
    keywords: List[str] = test.get("keywords", [])
    file_path = nodeid.split("::")[0]

    if file_path.startswith("tests/unit/"):
        if "test_rules.py" in file_path:
            return ("Phase 1", "Rule Filters / Ranking")
        if "test_counter_and_validation.py" in file_path:
            return ("Phase 1", "Counter & Validation")
        if "test_input_validation.py" in file_path:
            return ("Phase 1", "Input Validation")
        return ("Phase 1", "Unit")
    if file_path.startswith("tests/integration/") and "allocation" in file_path:
        return ("Phase 1", "Integration Pipeline")
    if file_path.startswith("tests/performance/") or "performance" in keywords:
        return ("Phase 1", "Performance")
    if file_path.startswith("tests/security/") or "security" in keywords:
        return ("Phase 1", "Security")
    if file_path.startswith("tests/observability/") or "observability" in keywords:
        return ("Phase 1", "Observability")
    if file_path.startswith("tests/ui/"):
        if "test_rtl_layout.py" in file_path:
            return ("Phase 2", "Localization/RTL")
        if "test_dashboard_page.py" in file_path:
            return ("Phase 2", "Dashboard & PDF")
        if "test_students_page.py" in file_path:
            return ("Phase 2", "Students CRUD & Export")
        if "test_import_export.py" in file_path:
            return ("Phase 2", "Import/Export")
        if "test_realtime.py" in file_path or "realtime" in keywords:
            return ("Phase 2", "Realtime")
        return ("Phase 2", "UI Automated")
    if file_path.startswith("tests/integration/") and "backend_sync" in file_path:
        return ("Phase 2", "Backend Sync (UI)")
    return ("Unknown", "Other")


def extract_failure_message(test: Dict[str, Any]) -> str:
    longrepr = test.get("longrepr")
    if isinstance(longrepr, str):
        lines = [line.strip() for line in longrepr.splitlines() if line.strip()]
        if lines:
            return lines[-1][:400]
    if isinstance(longrepr, dict):
        message = longrepr.get("reprcrash", {}).get("message")
        if message:
            return str(message)[:400]
        reprtrace = longrepr.get("reprtraceback")
        if isinstance(reprtrace, dict):
            entries = reprtrace.get("reprentries") or []
            for entry in reversed(entries):
                data = entry.get("data") if isinstance(entry, dict) else None
                if isinstance(data, dict):
                    text = data.get("repr")
                    if isinstance(text, str) and text.strip():
                        return text.strip().splitlines()[-1][:400]
    call = test.get("call") or {}
    message = call.get("longrepr") or call.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()[:400]
    return ""


def aggregate_tests(tests: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, Dict[str, Dict[str, int]]], List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, Any]]]:
    totals = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    phases: Dict[str, Dict[str, Dict[str, int]]] = {}
    failures: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    durations: List[Tuple[str, float]] = []

    for test in tests:
        outcome = test.get("outcome", "")
        nodeid = test.get("nodeid", "")
        phase, category = classify(test)
        phases.setdefault(phase, {})
        phases[phase].setdefault(category, {"pass": 0, "fail": 0, "skip": 0})

        totals["total"] += 1
        if outcome == "passed":
            totals["passed"] += 1
            phases[phase][category]["pass"] += 1
        elif outcome == "failed":
            totals["failed"] += 1
            phases[phase][category]["fail"] += 1
            failures.append({
                "nodeid": nodeid,
                "file": nodeid.split("::")[0],
                "message": extract_failure_message(test),
            })
        elif outcome == "skipped":
            totals["skipped"] += 1
            phases[phase][category]["skip"] += 1
            reason = ""
            longrepr = test.get("longrepr")
            if isinstance(longrepr, str):
                reason = longrepr.strip().splitlines()[0] if longrepr.strip() else ""
            elif isinstance(longrepr, dict):
                reason = longrepr.get("reprcrash", {}).get("message", "")
            skipped.append({"nodeid": nodeid, "reason": reason})

        duration = None
        call = test.get("call") or {}
        if isinstance(call, dict):
            duration = call.get("duration")
        if duration is None:
            duration = test.get("duration")
        if isinstance(duration, (int, float)):
            durations.append((nodeid, float(duration)))

    durations.sort(key=lambda item: item[1], reverse=True)
    slow_tests = [
        {"nodeid": nodeid, "duration_s": round(duration, 4)}
        for nodeid, duration in durations[:5]
    ]
    return totals, phases, failures, skipped, slow_tests


def parse_coverage(data: Dict[str, Any]) -> Tuple[float, str]:
    totals = data.get("totals", {})
    value = totals.get("percent_covered") or totals.get("percent_covered_display")
    try:
        pct = float(value)
    except Exception:  # noqa: BLE001
        pct = 0.0
    if pct >= 85:
        color = "brightgreen"
    elif pct >= 75:
        color = "yellow"
    else:
        color = "red"
    return pct, color


def parse_benchmarks(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], float]:
    rows = []
    max_mean_ms = 0.0
    for entry in data.get("benchmarks", []):
        name = entry.get("name") or entry.get("fullname") or "benchmark"
        stats = entry.get("stats") or {}
        mean = stats.get("mean")
        stddev = stats.get("stddev")
        rounds = stats.get("rounds")
        mean_ms = float(mean) * 1000.0 if isinstance(mean, (int, float)) else None
        stddev_ms = float(stddev) * 1000.0 if isinstance(stddev, (int, float)) else None
        if mean_ms is not None:
            max_mean_ms = max(max_mean_ms, mean_ms)
        rows.append(
            {
                "name": str(name),
                "mean_ms": round(mean_ms, 3) if mean_ms is not None else None,
                "stddev_ms": round(stddev_ms, 3) if stddev_ms is not None else None,
                "rounds": rounds,
            }
        )
    return rows, max_mean_ms


def make_badge(label: str, value: str, color: str) -> str:
    label_enc = quote_plus(label)
    value_enc = quote_plus(value)
    color_enc = quote_plus(color)
    return f"![{label}](https://img.shields.io/badge/{label_enc}-{value_enc}-{color_enc})"


def tests_badge(totals: Dict[str, int]) -> Tuple[str, str]:
    total = totals.get("total", 0)
    failed = totals.get("failed", 0)
    if total == 0:
        return "0/0", "lightgrey"
    color = "brightgreen" if failed == 0 else "red"
    return f"{totals.get('passed', 0)}/{total}", color


def performance_badge(gate: Dict[str, Any], max_mean_ms: float) -> Tuple[str, str]:
    breaches = gate.get("breaches") or []
    if breaches:
        return breaches[0].split(":")[0], "red"
    threshold = gate.get("threshold_ms")
    if max_mean_ms:
        value = f"{max_mean_ms:.1f} ms"
        if isinstance(threshold, (int, float)) and max_mean_ms > float(threshold):
            return value, "red"
        return value, "brightgreen"
    return "no data", "lightgrey"


def format_failures(failures: List[Dict[str, str]]) -> Tuple[List[str], List[str]]:
    if not failures:
        return ["- All tests passed."], [f"- {FA_STRINGS['all_passed']}"]
    en_lines = [f"- {item['nodeid']}: {item['message'] or 'See pytest output.'}" for item in failures]
    fa_lines = [f"- {item['nodeid']}: {item['message'] or FA_STRINGS['issues_detected']}" for item in failures]
    return en_lines, fa_lines


def format_skipped(skipped: List[Dict[str, str]]) -> Tuple[List[str], List[str]]:
    if not skipped:
        return ["- None"], [f"- {FA_STRINGS['no_skipped']}"]
    en = [f"- {item['nodeid']}: {item['reason']}" for item in skipped]
    fa = [f"- {item['nodeid']}: {item['reason']}" for item in skipped]
    return en, fa


def format_slow(slow_tests: List[Dict[str, Any]]) -> List[str]:
    if not slow_tests:
        return ["- n/a"]
    return [f"- {item['nodeid']} ({item['duration_s']} s)" for item in slow_tests]


def build_actions(
    failures: List[Dict[str, str]],
    coverage_pct: float,
    gate: Dict[str, Any],
    slow_tests: List[Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    en: List[str] = []
    fa: List[str] = []
    for failure in failures[:3]:
        nodeid = failure['nodeid']
        message = failure['message'] or 'See pytest output.'
        en.append(f"Investigate `{nodeid}` — {message}")
        fa.append(f"بررسی تست `{nodeid}` — {message}")
    if coverage_pct < 80:
        en.append("Increase test coverage to at least 80% before merging.")
        fa.append("پوشش تست را به حداقل ۸۰٪ برسانید.")
    breaches = gate.get("breaches") or []
    if breaches:
        en.append("Address performance regression: " + breaches[0])
        fa.append("رفع رگرسیون عملکرد: " + breaches[0])
    elif gate.get("passed") is False:
        en.append("Performance gate failed; review benchmark results.")
        fa.append("گیت عملکرد رد شد؛ نتایج بنچمارک را بررسی کنید.")
    for slow in slow_tests[:2]:
        nodeid = slow['nodeid']
        duration = slow['duration_s']
        en.append(f"Profile slow test `{nodeid}` ({duration}s).")
        fa.append(f"تست کند `{nodeid}` ({duration} ثانیه) را پروفایل کنید.")
    if not en:
        en.append("No immediate actions required; monitor upcoming runs.")
        fa.append("اقدام فوری نیاز نیست؛ اجرای بعدی را پایش کنید.")
    return en, fa


def render_phase_table(phases: Dict[str, Dict[str, Dict[str, int]]]) -> str:
    rows = ["| Phase | Category | ✅ Pass | ❌ Fail | ⚠️ Skip |", "| --- | --- | --- | --- | --- |"]
    for phase in sorted(phases.keys()):
        for category in sorted(phases[phase].keys()):
            stats = phases[phase][category]
            rows.append(
                f"| {phase} | {category} | {stats['pass']} | {stats['fail']} | {stats['skip']} |"
            )
    return "\n".join(rows)


def write_markdown(
    totals: Dict[str, int],
    coverage_pct: float,
    coverage_color: str,
    perf_gate: Dict[str, Any],
    max_mean_ms: float,
    failures: List[Dict[str, str]],
    skipped: List[Dict[str, str]],
    slow_tests: List[Dict[str, Any]],
    phases: Dict[str, Dict[str, Dict[str, int]]],
    selection: Dict[str, Any],
    actions_en: List[str],
    actions_fa: List[str],
) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)

    coverage_badge = make_badge("Coverage", f"{coverage_pct:.1f}%", coverage_color)
    tests_value, tests_color = tests_badge(totals)
    tests_badge_md = make_badge("Tests", tests_value, tests_color)
    perf_value, perf_color = performance_badge(perf_gate, max_mean_ms)
    perf_badge = make_badge("Performance", perf_value, perf_color)

    failures_en, failures_fa = format_failures(failures)
    skipped_en, skipped_fa = format_skipped(skipped)
    slow_lines = format_slow(slow_tests)

    selection_scope = selection.get("scope", "auto")
    selection_reason = selection.get("reason", "")
    selected_tests = selection.get("selected_tests") or []

    lines = [
        f"# Continuous Quality Report | {FA_STRINGS['report_title']}",
        "",
        f"## Badges | {FA_STRINGS['badges']}",
        f"- {coverage_badge}",
        f"- {tests_badge_md}",
        f"- {perf_badge}",
        "",
        f"## Summary | {FA_STRINGS['summary_heading']}",
        "**EN:** Automated quality checks completed.",
        f"**FA:** {FA_STRINGS['summary_done']}",
        "",
        f"## Test Outcomes | {FA_STRINGS['tests']}",
        "**EN:**",
    ]
    lines.extend(failures_en)
    lines.append("")
    lines.append("**FA:**")
    lines.extend(failures_fa)
    lines.extend([
        "",
        f"## Actions | {FA_STRINGS['actions']}",
        "**EN:**",
    ])
    lines.extend([f"- {item}" for item in actions_en])
    lines.append("")
    lines.append("**FA:**")
    lines.extend([f"- {item}" for item in actions_fa])
    lines.extend([
        "",
        f"## Selection | {FA_STRINGS['selection']}",
        f"- **Mode:** {selection_scope}",
        f"- **Reason:** {selection_reason}",
        f"- **Targets:** {', '.join(selected_tests) if selected_tests else FA_STRINGS['full_suite']}",
        "",
        f"## Slowest Tests | {FA_STRINGS['slow']}",
    ])
    lines.extend(slow_lines)
    lines.extend([
        "",
        f"## Skipped | {FA_STRINGS['skipped']}",
        "**EN:**",
    ])
    lines.extend(skipped_en)
    lines.append("")
    lines.append("**FA:**")
    lines.extend(skipped_fa)
    lines.extend([
        "",
        f"## Phase Breakdown | {FA_STRINGS['phase']}",
        render_phase_table(phases),
        "",
        f"## Performance | {FA_STRINGS['performance']}",
        f"- Max mean: {max_mean_ms:.2f} ms",
        f"- Gate status: {'passed' if perf_gate.get('passed', True) else 'failed'}",
    ])
    MARKDOWN_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_alert_if_needed(
    totals: Dict[str, int],
    failures: List[Dict[str, str]],
    gate: Dict[str, Any],
    coverage_pct: float,
    actions_en: List[str],
    actions_fa: List[str],
) -> None:
    need_alert = totals.get("failed", 0) > 0 or not gate.get("passed", True) or coverage_pct < 70
    if not need_alert:
        if ALERT_PATH.exists():
            ALERT_PATH.unlink()
        return
    REPORTS_DIR.mkdir(exist_ok=True)
    reasons_en: List[str] = []
    reasons_fa: List[str] = []
    if totals.get("failed", 0) > 0:
        reasons_en.append(f"{totals['failed']} failing tests")
        reasons_fa.append(f"{totals['failed']} \u062a\u0633\u062a \u0646\u0627\u0645\u0648\u0641\u0642")
    if not gate.get("passed", True):
        reasons_en.append("performance gate failed")
        reasons_fa.append("\u06af\u064a\u062a \u0639\u0645\u0644\u06a9\u0631\u062f \u0631\u062f \u0634\u062f")
    if coverage_pct < 70:
        reasons_en.append("coverage below 70%")
        reasons_fa.append("\u067e\u0648\u0634\u0634 \u0643\u0645\u062a\u0631 \u0627\u0632 ۷۰٪")
    lines = [
        f"# Alert | {FA_STRINGS['alert_title']}",
        "",
        "**EN:** Issues detected during automated checks.",
        f"**FA:** {FA_STRINGS['alert_intro']}",
        "",
        f"## Reasons | {FA_STRINGS['reasons']}",
        "**EN:** " + ", ".join(reasons_en),
        "**FA:** " + ", ".join(reasons_fa),
        "",
        f"## Next Steps | {FA_STRINGS['next_steps']}",
        "**EN:**",
    ]
    lines.extend([f"- {item}" for item in actions_en])
    lines.append("")
    lines.append("**FA:**")
    lines.extend([f"- {item}" for item in actions_fa])
    ALERT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    report = load_json(REPORT_PATH, {"tests": []})
    benchmark = load_json(BENCHMARK_PATH, {"benchmarks": []})
    coverage = load_json(COVERAGE_PATH, {"totals": {"percent_covered": 0.0}})
    gates = load_json(GATES_PATH, {"pytest": {}, "performance": {}})

    tests = report.get("tests", [])
    totals, phases, failures, skipped, slow_tests = aggregate_tests(tests)

    coverage_pct, coverage_color = parse_coverage(coverage)
    benchmark_rows, max_mean_ms = parse_benchmarks(benchmark)
    perf_gate = gates.get("performance", {})
    selection = gates.get("pytest", {})

    actions_en, actions_fa = build_actions(failures, coverage_pct, perf_gate, slow_tests)
    write_markdown(
        totals,
        coverage_pct,
        coverage_color,
        perf_gate,
        max_mean_ms,
        failures,
        skipped,
        slow_tests,
        phases,
        selection,
        actions_en,
        actions_fa,
    )
    write_alert_if_needed(totals, failures, perf_gate, coverage_pct, actions_en, actions_fa)

    summary = {
        "tests": {
            "overview": totals,
            "failures": failures,
            "skipped": skipped,
            "slow": slow_tests,
            "phases": phases,
        },
        "coverage": {
            "percent": coverage_pct,
            "color": coverage_color,
        },
        "performance": {
            "benchmarks": benchmark_rows,
            "max_mean_ms": max_mean_ms,
            "gate": perf_gate,
        },
        "selection": selection,
        "actions": {
            "en": actions_en,
            "fa": actions_fa,
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[generate_report] Wrote {SUMMARY_PATH} and {MARKDOWN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
