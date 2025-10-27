"""Regression coverage for Strict Scoring No-100 Gate behaviour."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
from typing import Dict, List

import pytest

from .test_parser_strict import PARSER


def _debug_payload(output: str, *, duration: float, namespace: str) -> Dict[str, object]:
    return {
        "namespace": namespace,
        "duration_sec": round(duration, 4),
        "output_sample": output.splitlines()[:8],
        "timestamp": time.perf_counter(),
    }


@pytest.fixture
def clean_state(tmp_path, request):
    """Ensure deterministic environment isolation before and after parser runs."""
    namespace = f"ci-parser-cap-{request.node.name}"
    sandbox = tmp_path / namespace
    sandbox.mkdir(parents=True, exist_ok=True)
    baseline_env = {key: os.environ.get(key) for key in list(os.environ.keys())}
    for key in list(os.environ.keys()):
        if key.startswith("CI_PARSER_TEST_"):
            os.environ.pop(key, None)
    os.environ["CI_PARSER_TEST_NAMESPACE"] = namespace
    try:
        yield {"namespace": namespace, "sandbox": sandbox}
    finally:
        for key in list(os.environ.keys()):
            if key not in baseline_env:
                os.environ.pop(key, None)
        for key, value in baseline_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _invoke_parser(args: List[str], summary: str, *, namespace: str) -> subprocess.CompletedProcess[str]:
    backoff_base = 0.01
    jitter = 0.0
    for attempt in range(3):
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(PARSER), "--summary-text", summary, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        duration = time.perf_counter() - start
        if proc.returncode == 0:
            return proc
        time.sleep(backoff_base * (2**attempt) + jitter)
        if attempt == 2:
            debug = _debug_payload(proc.stdout + proc.stderr, duration=duration, namespace=namespace)
            raise AssertionError(f"Parser execution failed after retries: {debug}")
    raise AssertionError("Parser execution exhausted retries without success")


def _extract_total(output: str) -> int:
    match = re.search(r"TOTAL:\s*(\d+)/100", output)
    if not match:
        raise AssertionError(f"TOTAL line missing in output: {output}")
    return int(match.group(1))


def test_no_100_gate_cap_and_clean(clean_state: Dict[str, object]) -> None:
    """Verify No-100 cap reduces totals and clean runs still achieve 100."""
    namespace = clean_state["namespace"]
    warning_summary = textwrap.dedent(
        """
        === 5 passed, 0 failed, 0 skipped, 2 warnings ===
        """
    ).strip()
    base_args = [
        "--gui-out-of-scope",
        "--evidence",
        "AGENTS.md::2 Setup & Commands",
        "--evidence",
        "AGENTS.md::3 Absolute Guardrails",
        "--evidence",
        "AGENTS.md::8 Testing & CI Gates",
        "--evidence",
        "AGENTS.md::10 User-Visible Errors",
    ]
    warning_result = _invoke_parser([*base_args, "--fail-under", "0"], warning_summary, namespace=namespace)
    warning_output = warning_result.stdout
    total_capped = _extract_total(warning_output)
    perf_match = re.search(r"Performance & Core:\s*(\d+)/40", warning_output)
    excel_match = re.search(r"Persian Excel:\s*(\d+)/40", warning_output)
    debug = {
        "namespace": namespace,
        "total": total_capped,
        "perf_line": perf_match.group(0) if perf_match else None,
        "excel_line": excel_match.group(0) if excel_match else None,
        "reason_block": warning_output.split("Reason for Cap", maxsplit=1)[-1],
    }
    assert warning_result.returncode == 0, warning_result.stderr
    assert "No-100 Gate" in warning_output, debug
    assert total_capped < 100, debug
    assert perf_match and int(perf_match.group(1)) <= 30, debug
    assert excel_match and int(excel_match.group(1)) <= 30, debug
    assert "TOTAL: 100/100" not in warning_output, debug

    clean_summary = textwrap.dedent(
        """
        === 3 passed, 0 failed, 0 skipped, 0 warnings ===
        """
    ).strip()
    clean_result = _invoke_parser([*base_args, "--fail-under", "100"], clean_summary, namespace=namespace)
    assert clean_result.returncode == 0, clean_result.stderr
    clean_output = clean_result.stdout
    assert "TOTAL: 100/100" in clean_output, clean_output
    assert "Reason for Cap (if any):\n- None" in clean_output, clean_output
