from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci_pytest_summary_parser.py"


@pytest.fixture(scope="module")
def ci_parser_module():
    spec = importlib.util.spec_from_file_location("ci_pytest_summary_parser", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.skip("ci parser module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_parser(summary: str, *, exit_code: int = 0, env: dict[str, str] | None = None, tmp_path: Path):
    summary_path = tmp_path / "summary.log"
    summary_path.write_text(summary, encoding="utf-8")
    exit_path = tmp_path / "exit.txt"
    exit_path.write_text(str(exit_code), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--summary-file", str(summary_path), "--exit-code-file", str(exit_path)],
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return result


def test_perfect_run_returns_success(ci_parser_module, tmp_path):
    raw_summary = "= 12 passed, 0 failed, 0 xfailed, 0 skipped, 0 warnings in 1.23s ="
    summary = ci_parser_module.extract_summary(raw_summary)
    assert summary.passed == 12
    assert summary.failed == 0
    report = _run_parser(raw_summary, tmp_path=tmp_path)
    assert report.returncode == 0, report.stdout
    payload = json.loads(report.stdout)
    assert payload["پیام"].startswith("✅"), payload
    assert payload["گزارش"]["هشدار"] == 0
    assert payload["Reason for Cap"] == "None"
    assert payload["Pytest Summary"]["passed"] == 12
    assert payload["امتیاز"]["محاسبه"]["جمع_پس_از_سقف"] == 100


def test_warnings_trigger_failure(tmp_path):
    noisy = "= 9 passed, 0 failed, 0 skipped, 1 warnings in 0.12s ="
    report = _run_parser(noisy, tmp_path=tmp_path)
    assert report.returncode == 1
    payload = json.loads(report.stdout)
    assert payload["پیام"].startswith("❌ اجرای تست‌ها ناموفق شد؛ شمار هشدارها باید صفر باشد."), payload
    assert "هشدارها=1" in payload["Reason for Cap"]


def test_malformed_summary_is_handled(ci_parser_module):
    messy = """
    --------
    random noise
    ==   ۳ passed ;; ۲ failed ;; ۱ warnings ==
    """
    summary = ci_parser_module.extract_summary(dedent(messy))
    assert summary.passed == 3
    assert summary.failed == 2
    assert summary.warnings == 1


def test_mixed_digits_and_ansi(tmp_path, ci_parser_module):
    ansi_summary = "\x1b[32m= ۱۲ passed, ۰ failed, ۰ xfailed, ۰ skipped, ۰ warnings in 0.03s =\x1b[0m"
    summary = ci_parser_module.extract_summary(ansi_summary)
    assert summary.passed == 12
    assert summary.failed == 0
    result = _run_parser(ansi_summary, tmp_path=tmp_path)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["گزارش"]["موفق"] == 12


def test_missing_fields_default_to_zero(ci_parser_module):
    raw = "= 5 passed in 0.01s ="
    summary = ci_parser_module.extract_summary(raw)
    assert summary.passed == 5
    assert summary.failed == 0
    assert summary.warnings == 0


def test_huge_input_uses_last_summary(ci_parser_module):
    tail = "\n".join(f"noise line {i}" for i in range(10_000))
    raw = f"{tail}\n= 1 passed in 0.01s ="
    summary = ci_parser_module.extract_summary(raw)
    assert summary.passed == 1
    assert summary.failed == 0
    assert summary.warnings == 0


def test_extremely_large_input_is_clamped(ci_parser_module):
    filler = "X" * 210_000
    raw = f"{filler}= ۳ passed, ۰ failed, ۰ warnings ="
    summary = ci_parser_module.extract_summary(raw)
    assert summary.passed == 3
    assert summary.failed == 0


def test_null_like_tokens_treated_as_zero(ci_parser_module, tmp_path):
    raw = "= None passed, null failed, '' warnings ="
    summary = ci_parser_module.extract_summary(raw)
    assert summary.passed == 0
    assert summary.failed == 0
    assert summary.warnings == 0
    result = _run_parser(raw, tmp_path=tmp_path)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["گزارش"]["موفق"] == 0


def test_nonzero_exit_code_raises_failure(tmp_path):
    summary = "= 2 passed, 0 failed, 0 warnings in 0.05s ="
    result = _run_parser(summary, exit_code=1, tmp_path=tmp_path)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["پیام"].startswith("❌ اجرای تست‌ها ناموفق شد؛ شمار خطاها باید صفر باشد."), payload
