from __future__ import annotations

"""Generate the Strict Scoring v2 quality report after pytest completes."""

import json
import os
import re
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

PYTEST_JSON = Path(os.environ.get("PYTEST_JSON", "reports/pytest.json"))
SUMMARY_TXT = Path("reports/pytest-summary.txt")

ALLOWED_OUTCOMES = ("passed", "failed", "skipped", "xfailed", "xpassed", "error")

SUMMARY_TOKEN_PATTERN = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|errors?|skipped|xfailed|xpassed|warnings?)",
    re.IGNORECASE,
)


@dataclass
class SpecRequirement:
    name: str
    axis: str
    evidences: List[str]
    passed: bool = False


class Score:
    def __init__(self, gui_in_scope: bool) -> None:
        self.base_max = {"perf": 40, "excel": 40, "gui": 15, "sec": 5}
        self.reallocation = {"perf": 0, "excel": 0, "gui": 0, "sec": 0}
        if not gui_in_scope:
            self.reallocation["perf"] = 9
            self.reallocation["excel"] = 6
            self.reallocation["gui"] = -15
        self.deductions = {axis: 0 for axis in self.base_max}
        self.caps: List[str] = []

    def deduct(self, axis: str, amount: int) -> None:
        if axis not in self.deductions:
            return
        self.deductions[axis] += amount

    def capacity(self, axis: str) -> int:
        return self.base_max[axis] + self.reallocation.get(axis, 0)

    def total_value(self, axis: str) -> int:
        capacity = self.capacity(axis)
        deduction = self.deductions[axis]
        return max(0, min(capacity, capacity - deduction))

    def display_value(self, axis: str) -> int:
        base = self.base_max[axis]
        return min(base, self.total_value(axis))

    def bonus_value(self, axis: str) -> int:
        bonus = self.reallocation.get(axis, 0)
        if bonus <= 0:
            return 0
        return max(0, min(bonus, self.total_value(axis) - self.display_value(axis)))

    def total(self) -> int:
        return sum(self.total_value(axis) for axis in self.base_max)


SPEC_ITEMS: List[Tuple[str, str, Tuple[str, ...]]] = [
    (
        "Determinism (injected clock, tz=Asia/Tehran; no datetime.now())",
        "perf",
        (
            "tests/time/test_no_wallclock_repo_guard.py::test_no_wall_clock_calls_in_repo",
            "AGENTS.md::Determinism",
        ),
    ),
    (
        "Middleware order RateLimit→Idempotency→Auth",
        "perf",
        (
            "tests/middleware/test_order_post.py::test_middleware_order_post_exact",
            "AGENTS.md::Middleware order (MUST)",
        ),
    ),
    (
        "Excel safety & Persian hygiene",
        "excel",
        (
            "tests/export/test_csv_excel_hygiene.py::test_formula_guard_and_crlf_preserved",
            "AGENTS.md::Excel-safety",
        ),
    ),
    (
        "Atomic streaming writer (.part→fsync→rename)",
        "excel",
        ("tests/export/test_csv_excel_hygiene.py::test_atomic_streaming_writes",),
    ),
    (
        "Exporter debug artifacts mask PII",
        "excel",
        ("tests/export/test_csv_excel_hygiene.py::test_export_failure_creates_debug_artifact",),
    ),
    (
        "Performance budgets (exporter p95<15s & mem cap)",
        "perf",
        ("tests/perf/test_exporter_perf.py::test_exporter_perf_budgets",),
    ),
    (
        "Persian error envelopes deterministic",
        "excel",
        ("tests/middleware/test_order_post.py::test_persian_error_envelopes_deterministic",),
    ),
    (
        "Observability (retry metrics & masked logs)",
        "sec",
        (
            "tests/retry/test_retry_backoff_metrics.py::test_exhaustion_and_histograms",
            "tests/plugins/test_plugin_stubs.py::test_logs_mask_pii",
        ),
    ),
    (
        "Security: /metrics token guard enforced",
        "sec",
        ("tests/middleware/test_order_post.py::test_metrics_token_guard",),
    ),
    (
        "Retry exhaustion & fatal classification",
        "perf",
        (
            "tests/retry/test_retry_backoff_metrics.py::test_retry_exhaustion_records_metrics",
            "tests/retry/test_retry_backoff_metrics.py::test_retry_fatal_records_metric",
        ),
    ),
    (
        "State hygiene (Redis namespaces & CollectorRegistry reset)",
        "perf",
        (
            "tests/idem/test_concurrent_posts.py::test_only_one_succeeds",
            "tests/plugins/test_plugin_stubs.py::test_prom_registry_is_reset",
        ),
    ),
    (
        "Edge input normalisation (None/0/'0'/ZW/mixed digits)",
        "excel",
        ("tests/domain/test_validate_registration.py::test_phase1_normalization_edges",),
    ),
    (
        "Validation rules enforce enums & regex",
        "perf",
        ("tests/domain/test_validate_registration.py::test_validation_rules_raise",),
    ),
    (
        "Counter derivations & regex alignment",
        "perf",
        ("tests/domain/test_validate_registration.py::test_counter_derivations_and_regex",),
    ),
    (
        "Derived fields: gender_prefix/year_code/StudentType",
        "perf",
        ("tests/domain/test_validate_registration.py::test_derived_fields",),
    ),
    (
        "Plugin compatibility (xdist/timeout stubs)",
        "perf",
        (
            "tests/plugins/test_plugin_stubs.py::test_xdist_stub_accepts_short_option",
            "tests/plugins/test_plugin_stubs.py::test_stub_bails_when_real_plugin_present",
        ),
    ),
    (
        "Idempotency keys unique per request",
        "perf",
        ("tests/idem/test_concurrent_posts.py::test_unique_idempotency_keys_per_request",),
    ),
    (
        "Sensitive columns always quoted in exports",
        "excel",
        ("tests/export/test_csv_excel_hygiene.py::test_sensitive_cols_always_quoted",),
    ),
]

SPEC_REQUIREMENTS: List[SpecRequirement] = [
    SpecRequirement(name=name, axis=axis, evidences=list(evidences))
    for name, axis, evidences in SPEC_ITEMS
]

EXPECTED_SPEC_SIGNATURE = "9311486e49b8685113fb6c8f5f2b6b15"

GUI_IN_SCOPE = any(spec.axis == "gui" for spec in SPEC_REQUIREMENTS)

_AGENTS_TEXT_CACHE: str | None = None


def enforce_spec_freeze() -> None:
    """Fail fast if spec evidence mapping drifts from the frozen contract."""

    current_signature = blake2b(
        repr(
            [
                (spec.name, spec.axis, tuple(spec.evidences))
                for spec in SPEC_REQUIREMENTS
            ]
        ).encode("utf-8"),
        digest_size=16,
    ).hexdigest()
    if current_signature != EXPECTED_SPEC_SIGNATURE:
        raise SystemExit(
            "Spec evidence map drift detected; update SPEC_ITEMS only with explicit approval."
        )
    if not any("AGENTS.md::" in evidence for _, _, evidences in SPEC_ITEMS for evidence in evidences):
        raise SystemExit("Spec evidence map must reference AGENTS.md at least once.")


def parse_json_summary() -> Dict[str, int]:
    if not PYTEST_JSON.exists():
        raise SystemExit("Pytest JSON report missing; rerun pytest with --json-report.")
    data = json.loads(PYTEST_JSON.read_text(encoding="utf-8"))
    tallies = {key: 0 for key in ALLOWED_OUTCOMES}
    unexpected: List[str] = []
    entries = data.get("tests", [])
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("Malformed pytest JSON: each test entry must be an object.")
        outcome = entry.get("outcome")
        nodeid = entry.get("nodeid", "<unknown>")
        if outcome in tallies:
            tallies[outcome] += 1
        else:
            unexpected.append(f"{nodeid}→{outcome}")
    if unexpected:
        raise SystemExit(
            "Unexpected pytest outcomes present in JSON report: {}".format(
                ", ".join(sorted(unexpected))
            )
        )
    total_tests = len(entries)
    tallied_tests = sum(tallies.values())
    if total_tests != tallied_tests:
        raise SystemExit(
            "Pytest JSON entries ({}) do not match tallied outcomes ({}); rerun pytest.".format(
                total_tests, tallied_tests
            )
        )
    summary = data.get("summary") or {}
    summary_counts: Dict[str, int] = {}
    for key in ALLOWED_OUTCOMES:
        summary_value = summary.get(key)
        if summary_value is None:
            if key == "error":
                summary_value = summary.get("errors")
            elif key == "failed":
                summary_value = summary.get("failures")
            elif key == "xfailed":
                summary_value = summary.get("xfail")
            elif key == "xpassed":
                summary_value = summary.get("xpass")
        if summary_value is None:
            summary_value = 0
        summary_counts[key] = int(summary_value)
        if summary_counts[key] != tallies[key]:
            raise SystemExit(
                "Pytest JSON summary mismatch for {}: summary={}, entries={}".format(
                    key, summary_counts[key], tallies[key]
                )
            )
    warnings_list = data.get("warnings", [])
    warnings_summary = summary.get("warnings")
    if warnings_summary is None:
        warnings_summary = len(warnings_list)
    warnings_summary = int(warnings_summary)
    summary_counts["warnings"] = warnings_summary
    if warnings_summary != len(warnings_list):
        raise SystemExit(
            "Warnings count mismatch: summary={}, warnings entries={}".format(
                warnings_summary, len(warnings_list)
            )
        )
    if warnings_summary:
        raise SystemExit(
            "Pytest run emitted warnings despite -W error requirement; fix warnings before scoring."
        )
    return summary_counts


def parse_text_summary() -> Dict[str, int]:
    if not SUMMARY_TXT.exists():
        raise SystemExit(
            "Pytest terminal summary not captured; pipe pytest output to reports/pytest-summary.txt."
        )
    content = SUMMARY_TXT.read_text(encoding="utf-8")
    content = re.sub(r"\x1b\[[0-9;]*m", "", content)
    tokens = {key: 0 for key in ALLOWED_OUTCOMES}
    tokens["warnings"] = 0
    found = False
    for match in SUMMARY_TOKEN_PATTERN.finditer(content):
        found = True
        count = int(match.group("count"))
        label = match.group("label").lower()
        if label in {"warning", "warnings"}:
            tokens["warnings"] = count
        elif label in {"error", "errors"}:
            tokens["error"] = count
        else:
            tokens[label] = count
    if not found:
        passed_match = re.search(r"(?P<count>\d+)\s+passed\b", content)
        if passed_match:
            tokens["passed"] = int(passed_match.group("count"))
        else:
            raise SystemExit("Unable to parse pytest terminal summary from reports/pytest-summary.txt.")
    return tokens


def load_summary() -> Dict[str, int]:
    json_summary = parse_json_summary()
    text_summary = parse_text_summary()
    for key in ALLOWED_OUTCOMES:
        json_summary.setdefault(key, 0)
        text_summary.setdefault(key, 0)
    json_summary.setdefault("warnings", 0)
    text_summary.setdefault("warnings", 0)
    if json_summary != text_summary:
        raise SystemExit(
            "Mismatch between pytest JSON and terminal summary; investigate run consistency."
        )
    return json_summary


def load_test_entries() -> List[Dict[str, Any]]:
    if not PYTEST_JSON.exists():
        return []
    data = json.loads(PYTEST_JSON.read_text(encoding="utf-8"))
    entries: List[Dict[str, Any]] = []
    for entry in data.get("tests", []):
        if not isinstance(entry, dict):
            raise SystemExit("Malformed pytest JSON: each test entry must be an object.")
        entries.append(entry)
    return entries


def ensure_entry_consistency(summary: Dict[str, int], entries: Iterable[Dict[str, Any]]) -> None:
    """Ensure individual test outcomes align with the aggregated summary."""

    allowed = set(ALLOWED_OUTCOMES)
    entries_list = list(entries)
    tallies = {key: 0 for key in allowed}
    unexpected: List[str] = []
    for entry in entries_list:
        outcome = entry.get("outcome")
        nodeid = entry.get("nodeid", "<unknown>")
        if outcome in allowed:
            tallies[outcome] += 1
        else:
            unexpected.append(f"{nodeid}→{outcome}")
    for key in allowed:
        if summary.get(key, 0) != tallies[key]:
            raise SystemExit(
                "Pytest summary count mismatch for {}: summary={}, entries={}".format(
                    key, summary.get(key, 0), tallies[key]
                )
            )
    if unexpected:
        raise SystemExit(
            "Unexpected pytest outcomes present: {}".format(
                ", ".join(sorted(unexpected))
            )
        )
    entries_count = sum(tallies.values())
    if entries_count != len(entries_list):
        raise SystemExit(
            "Pytest test count mismatch: expected {} entries, tallied {}.".format(
                len(entries_list), entries_count
            )
        )


def build_test_outcomes(entries: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    outcomes: Dict[str, str] = {}
    for entry in entries:
        nodeid = entry.get("nodeid")
        outcome = entry.get("outcome")
        if nodeid and outcome:
            outcomes[nodeid] = outcome
    return outcomes


def evidence_passed(evidence: str, tests: Dict[str, str]) -> bool:
    if evidence.startswith("tests/"):
        outcome = tests.get(evidence)
        if outcome == "passed":
            return True
        return any(
            nodeid.startswith(f"{evidence}[") and result == "passed"
            for nodeid, result in tests.items()
        )
    if evidence.startswith("AGENTS.md::"):
        global _AGENTS_TEXT_CACHE
        if _AGENTS_TEXT_CACHE is None:
            _AGENTS_TEXT_CACHE = Path("AGENTS.md").read_text(encoding="utf-8")
        _, marker = evidence.split("::", 1)
        return marker.strip() in _AGENTS_TEXT_CACHE
    if "::" in evidence:
        path_str, symbol = evidence.split("::", 1)
        path = Path(path_str)
        if not path.exists():
            return False
        return symbol in path.read_text(encoding="utf-8")
    path = Path(evidence)
    return path.exists()


def count_todos(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        total += text.count("TODO") + text.count("FIXME")
    return total


def extract_reason(entry: Dict[str, Any]) -> str:
    longrepr = entry.get("longrepr")
    if not longrepr:
        return ""
    if isinstance(longrepr, str):
        return longrepr
    if isinstance(longrepr, dict):
        if "reprcrash" in longrepr:
            crash = longrepr.get("reprcrash", {})
            message = str(crash.get("message", ""))
            path = str(crash.get("path", ""))
            return f"{path} {message}".strip()
        if "reprtext" in longrepr:
            return str(longrepr["reprtext"])
        return " ".join(str(value) for value in longrepr.values())
    return str(longrepr)


def main() -> None:
    agents_path = Path("AGENTS.md")
    if not agents_path.exists():
        raise SystemExit("پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید.")

    global _AGENTS_TEXT_CACHE
    _AGENTS_TEXT_CACHE = agents_path.read_text(encoding="utf-8")

    enforce_spec_freeze()

    required_env = {
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_PLUGINS": "pytest_env.plugin",
        "TZ": "Asia/Tehran",
    }
    for key, expected in required_env.items():
        actual = os.environ.get(key)
        if actual != expected:
            raise SystemExit(f"Expected {key}={expected!r} when generating strict report; got {actual!r}.")

    warnings_flag = os.environ.get("PYTHONWARNINGS", "").lower()
    summary_text = SUMMARY_TXT.read_text(encoding="utf-8") if SUMMARY_TXT.exists() else ""
    addopts = os.environ.get("PYTEST_ADDOPTS", "")
    command_env = os.environ.get("PYTEST_COMMAND", "")
    if not any("-W error" in value or "-Werror" in value for value in (summary_text, addopts, command_env)) and not warnings_flag.startswith("error"):
        raise SystemExit("Pytest run must enable -W error; rerun with pytest -W error ...")

    summary = load_summary()
    entries = load_test_entries()
    ensure_entry_consistency(summary, entries)
    tests = build_test_outcomes(entries)
    score = Score(gui_in_scope=GUI_IN_SCOPE)

    for spec in SPEC_REQUIREMENTS:
        spec.passed = all(evidence_passed(evidence, tests) for evidence in spec.evidences)
        if not spec.passed:
            score.deduct(spec.axis, 3)

    spec_lookup = {spec.name: spec for spec in SPEC_REQUIREMENTS}

    if not spec_lookup["Middleware order RateLimit→Idempotency→Auth"].passed:
        score.deduct("perf", 10)
    if not spec_lookup["State hygiene (Redis namespaces & CollectorRegistry reset)"].passed:
        score.deduct("perf", 8)
    if not spec_lookup["Retry exhaustion & fatal classification"].passed:
        score.deduct("perf", 6)
    if not spec_lookup["Determinism (injected clock, tz=Asia/Tehran; no datetime.now())"].passed:
        score.deduct("perf", 5)

    integration_evidences = {
        evidence
        for spec in SPEC_REQUIREMENTS
        for evidence in spec.evidences
        if evidence.startswith("tests/")
    }
    if len(integration_evidences) < 3:
        score.deduct("perf", 3)
        score.deduct("excel", 3)

    agents_evidence_present = any(
        evidence.startswith("AGENTS.md::") and evidence_passed(evidence, tests)
        for spec in SPEC_REQUIREMENTS
        for evidence in spec.evidences
    )
    if not agents_evidence_present:
        score.deduct("perf", 3)
        score.deduct("excel", 3)

    todo_count = count_todos(Path("tooling").rglob("*.py"))
    if todo_count:
        score.deduct("perf", min(10, 2 * todo_count))

    if summary.get("xfailed", 0) or summary.get("skipped", 0):
        score.caps.append("cap=92 (skipped/xfailed present)")
    if summary.get("warnings", 0):
        score.caps.append("cap=90 (warnings present)")
    if summary.get("failed", 0):
        score.caps.append("cap=85 (failures present)")
    if summary.get("error", 0):
        score.caps.append("cap=85 (errors present)")
    if summary.get("xpassed", 0):
        score.caps.append("cap=92 (xpassed present)")

    def has_reason(entries_iter: Iterable[Dict[str, Any]], keywords: Iterable[str]) -> bool:
        lowered = [kw.lower() for kw in keywords]
        for entry in entries_iter:
            if entry.get("outcome") != "skipped":
                continue
            reason = extract_reason(entry).lower()
            if any(keyword in reason for keyword in lowered):
                return True
        return False

    if has_reason(entries, ["missing", "not installed", "importorskip", "dependency", "unavailable", "fake-only"]):
        score.caps.append("cap=85 (missing dependency or fake-only skip detected)")

    if has_reason(entries, ["service", "redis launch skipped", "requires external service", "service unavailable"]):
        score.caps.append("cap=89 (service skip detected)")

    next_actions: List[str] = []
    if next_actions:
        score.caps.append("cap=95 (next actions outstanding)")

    total = score.total()
    for cap in score.caps:
        cap_value = int(cap.split("=")[1].split()[0])
        if total > cap_value:
            total = cap_value

    level = "Excellent" if total >= 95 else "Good" if total >= 85 else "Average" if total >= 70 else "Poor"

    integration_quality = {
        "State cleanup fixtures": spec_lookup["State hygiene (Redis namespaces & CollectorRegistry reset)"].passed,
        "Retry mechanisms": spec_lookup["Retry exhaustion & fatal classification"].passed,
        "Debug helpers": spec_lookup["Exporter debug artifacts mask PII"].passed,
        "Middleware order awareness": spec_lookup["Middleware order RateLimit→Idempotency→Auth"].passed,
        "Concurrent safety": spec_lookup["State hygiene (Redis namespaces & CollectorRegistry reset)"].passed,
    }

    runtime_robustness = {
        "Handles dirty Redis state": spec_lookup["State hygiene (Redis namespaces & CollectorRegistry reset)"].passed,
        "Rate limit awareness": spec_lookup["Middleware order RateLimit→Idempotency→Auth"].passed,
        "Timing controls": spec_lookup["Determinism (injected clock, tz=Asia/Tehran; no datetime.now())"].passed,
        "CI environment ready": spec_lookup["Observability (retry metrics & masked logs)"].passed
        and spec_lookup["State hygiene (Redis namespaces & CollectorRegistry reset)"].passed,
    }

    strengths = [spec.name for spec in SPEC_REQUIREMENTS if spec.passed][:2]
    weaknesses = [spec.name for spec in SPEC_REQUIREMENTS if not spec.passed][:2]

    print("════════ 5D+ QUALITY ASSESSMENT REPORT ════════")
    print(
        "Performance & Core: {}/40 | Persian Excel: {}/40 | GUI: {}/15 | Security: {}/5".format(
            score.display_value("perf"),
            score.display_value("excel"),
            score.display_value("gui"),
            score.display_value("sec"),
        )
    )
    print(f"TOTAL: {total}/100 → Level: {level}")

    print("\nPytest Summary:")
    print(
        "- passed={passed}, failed={failed}, errors={errors}, xfailed={xfailed}, xpassed={xpassed}, "
        "skipped={skipped}, warnings={warnings}".format(
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            errors=summary.get("error", 0),
            xfailed=summary.get("xfailed", 0),
            xpassed=summary.get("xpassed", 0),
            skipped=summary.get("skipped", 0),
            warnings=summary.get("warnings", 0),
        )
    )

    print("\nIntegration Testing Quality:")
    for label, ok in integration_quality.items():
        print(f"- {label}: {'✅' if ok else '❌'}")

    print("\nSpec compliance:")
    for spec in SPEC_REQUIREMENTS:
        mark = "✅" if spec.passed else "❌"
        evidence_str = ", ".join(spec.evidences)
        print(f"- {mark} {spec.name} — evidence: {evidence_str}")

    print("\nRuntime Robustness:")
    for label, ok in runtime_robustness.items():
        print(f"- {label}: {'✅' if ok else '❌'}")

    print("\nReason for Cap (if any):")
    if score.caps:
        for cap in score.caps:
            print(f"- {cap}")
    else:
        print("- None")

    print("\nScore Derivation:")
    print(
        "- Raw axis: Perf={}/40, Excel={}/40, GUI={}/15, Sec={}/5".format(
            score.base_max["perf"],
            score.base_max["excel"],
            score.base_max["gui"],
            score.base_max["sec"],
        )
    )
    print(
        "- Reallocation bonus: Perf={:+}, Excel={:+}, GUI={:+}, Sec={:+}".format(
            score.reallocation["perf"],
            score.reallocation["excel"],
            score.reallocation["gui"],
            score.reallocation["sec"],
        )
    )
    print(
        "- Deductions: Perf=-{}, Excel=-{}, GUI=-{}, Sec=-{}".format(
            score.deductions["perf"],
            score.deductions["excel"],
            score.deductions["gui"],
            score.deductions["sec"],
        )
    )
    print(
        "- Clamped axis: Perf={}/40, Excel={}/40, GUI={}/15, Sec={}/5".format(
            score.display_value("perf"),
            score.display_value("excel"),
            score.display_value("gui"),
            score.display_value("sec"),
        )
    )
    caps_output = ", ".join(score.caps) if score.caps else "None"
    print(f"- Caps applied: {caps_output}")
    print(
        "- Final axis (incl. reallocation): Perf={}, Excel={}, GUI={}, Sec={}".format(
            score.total_value("perf"),
            score.total_value("excel"),
            score.total_value("gui"),
            score.total_value("sec"),
        )
    )
    print(f"- TOTAL={total}")

    print("\nTop strengths:")
    if strengths:
        for idx, item in enumerate(strengths, start=1):
            print(f"{idx}) {item}")
    else:
        print("1) None")
    print("\nCritical weaknesses:")
    if weaknesses:
        for idx, item in enumerate(weaknesses, start=1):
            print(f"{idx}) {item}")
    else:
        print("1) None")

    print("\nNext actions:")
    if next_actions:
        for item in next_actions:
            print(f"[ ] {item}")
    else:
        print("- None")

    if total < 100:
        raise SystemExit("Strict scoring below 100; see report above for blocking items.")


if __name__ == "__main__":
    main()
