from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.strict_score_core import EvidenceMatrix, ScoreEngine
from tools.strict_score_reporter import (
    StrictMetadata,
    StrictScoreLogger,
    StrictScoreMetrics,
    StrictScoreWriter,
    build_fallback_payload,
    parse_pytest_summary_extended,
)


def _debug_listing(path: Path) -> str:
    entries = sorted(item.name for item in path.iterdir()) if path.exists() else []
    return f"path={path} entries={entries}"


def test_parse_pytest_summary_extended_handles_persian_digits() -> None:
    text = "=================\n= ۱۲\u200c passed, ٠ failed, ۵ skipped, ۰ xfailed, ۱ warnings =\n================="
    counts, found = parse_pytest_summary_extended(text)
    assert found, "Pytest summary with Persian digits should be detected"
    assert counts["passed"] == 12
    assert counts["failed"] == 0
    assert counts["skipped"] == 5
    assert counts["warnings"] == 1


def test_strict_score_writer_atomic(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "strict_score.json"
    metadata = StrictMetadata(
        phase="synthesize",
        correlation_id="cid-1234",
        clock_seed="seed",
        path=target,
        pythonwarnings="default",
    )
    payload = build_fallback_payload(metadata=metadata)
    log_stream = io.StringIO()
    logger = StrictScoreLogger(stream=log_stream, correlation_id="cid-1234")
    metrics = StrictScoreMetrics()
    writer = StrictScoreWriter(logger=logger, metrics=metrics)
    writer.write(path=target, payload=payload, mode="synth")
    assert target.exists(), _debug_listing(target.parent)
    leftovers = [p for p in target.parent.iterdir() if p.suffix == ".part"]
    assert not leftovers, f"temporary files leaked: {leftovers}"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["report_mode"] == "synth"


@pytest.mark.parametrize("phase,expected_mode", [("synthesize", "synth"), ("test", "real")])
def test_cli_guard_creates_report(tmp_path: Path, phase: str, expected_mode: str) -> None:
    target = tmp_path / "reports" / "strict_score.json"
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "default" if phase == "synthesize" else "error"
    args = [
        sys.executable,
        "-m",
        "tools.strict_score_guard",
        "--phase",
        phase,
        "--json",
        str(target),
    ]
    if phase == "test":
        args.extend(
            [
                "--summary-text",
                "=================\n= 3 passed, 1 skipped, 0 failed, 0 xfailed, 0 warnings =\n=================",
            ]
        )
    result = subprocess.run(args, env=env, text=True, capture_output=True, check=False, timeout=30)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert target.exists(), _debug_listing(target.parent)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["report_mode"] == expected_mode
    json_logs = []
    report_lines = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            json_logs.append(json.loads(line))
        except json.JSONDecodeError:
            report_lines.append(line)
    assert json_logs, "expected JSON logs on stdout"
    assert json_logs[-1]["event"] == "strict_report.completed"
    assert json_logs[-1]["correlation_id"] == payload["correlation_id"]
    report_text = "\n".join(report_lines)
    assert "QUALITY ASSESSMENT REPORT" in report_text


def test_guard_with_full_evidence_scores_100(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "strict_score.json"
    evidence_file = tmp_path / "evidence.md"
    evidence_entries = [
        "- state_hygiene: tests/obs/test_prom_registry_reset.py::test_registry_fresh_between_tests",
        "- stable_sort_keys: tests/exports/test_sabt_core.py::test_stable_sort_order",
        "- chunking_filenames: tests/exports/test_sabt_core.py::test_chunking_and_naming_determinism",
        "- excel_safety: tests/exports/test_excel_safety_ci.py::test_quotes_formula_guard_crlf_bom",
        "- snapshot_delta: tests/exports/test_delta_window.py::test_delta_no_gap_overlap",
        "- atomic_finalize: tests/exports/test_manifest.py::test_atomic_manifest_after_files",
        "- counter_year_code: tests/counter/test_counter_rules.py::test_regex_and_gender_prefix",
        "- security_access: tests/security/test_metrics_and_downloads.py::test_token_and_signed_url",
        "- observability_metrics: tests/obs/test_export_metrics.py::test_export_metrics_labels_and_token_guard",
        "- slo_baseline: tests/perf/test_export_100k.py::test_p95_and_mem_budget",
        "- quality_gates: tests/ci/test_no_warnings_gate.py::test_warnings_are_errors",
    ]
    evidence_file.write_text("\n".join(evidence_entries), encoding="utf-8")
    summary_block = "=================\n= 8 passed, 0 failed, 0 skipped, 0 xfailed, 0 warnings =\n================="
    args = [
        sys.executable,
        "-m",
        "tools.strict_score_guard",
        "--phase",
        "test",
        "--json",
        str(target),
        "--summary-text",
        summary_block,
        "--evidence-file",
        str(evidence_file),
    ]
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "error"
    env["STRICT_SCORE_TODO_OVERRIDE"] = "0"
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=30, env=env)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["report_mode"] == "real"
    assert payload["scorecard"]["total"] == 100.0
    human_lines: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            human_lines.append(line)
    total_line = next(line for line in human_lines if line.startswith("TOTAL:"))
    assert f"TOTAL: {payload['scorecard']['total']:.1f}/100" in total_line


def test_guard_synth_report_matches_payload(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "strict_score.json"
    args = [
        sys.executable,
        "-m",
        "tools.strict_score_guard",
        "--phase",
        "install",
        "--json",
        str(target),
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONWARNINGS", "default")
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=30, env=env)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["report_mode"] == "synth"
    assert "scorecard" in payload and "total" in payload["scorecard"]
    human_lines: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            human_lines.append(line)
    total_line = next(line for line in human_lines if line.startswith("TOTAL:"))
    assert f"TOTAL: {payload['scorecard']['total']:.1f}/100" in total_line
    synth_reason = next((cap["reason"] for cap in payload.get("caps", []) if cap.get("reason")), "")
    assert synth_reason, "expected synth cap reason present"
    assert any(synth_reason in line for line in human_lines if "cap=" in line)


def test_summary_parse_and_evidence() -> None:
    summary = "=================\n= 5 passed, 0 failed, 0 skipped, 0 xfailed, 0 warnings =\n================="
    counts, found = parse_pytest_summary_extended(summary)
    assert found and counts["warnings"] == 0
    matrix = EvidenceMatrix()
    matrix.add("quality_gates", "tests/ci/test_no_warnings_gate.py::test_warnings_are_errors")
    engine = ScoreEngine(gui_in_scope=False, evidence=matrix)
    statuses = engine.apply_evidence_matrix()
    assert statuses["quality_gates"], "quality gates evidence should be recognized"
