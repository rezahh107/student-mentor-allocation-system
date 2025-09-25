"""آزمون‌های تکمیلی برای درگاه پوشش legacy."""
from __future__ import annotations

import builtins
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.coverage_gate as coverage_gate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_gate(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """اجرای اسکریپت پوشش در حالت خلاصه برای تست یکپارچه."""

    command = [sys.executable, "-m", "scripts.coverage_gate", "--summary", *args]
    merged_env = os.environ.copy()
    merged_env.update(env)
    merged_env.setdefault("PYTHONPATH", str(PROJECT_ROOT))
    merged_env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return subprocess.run(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )


def test_threshold_alias_and_clamp_high() -> None:
    """آستانهٔ بزرگ باید به ۱۰۰ همراه هشدار فارسی محدود شود."""

    threshold, warnings = coverage_gate._resolve_threshold("150", None)
    assert threshold == 100.0
    assert any("COV_INVALID_INPUT_CLAMPED" in warning for warning in warnings)


def test_threshold_negative_resets_to_default() -> None:
    """مقادیر منفی باید به ۹۵ همراه هشدار برگردند."""

    threshold, warnings = coverage_gate._resolve_threshold("-5", None)
    assert threshold == coverage_gate.DEFAULT_THRESHOLD
    assert any("COV_INVALID_INPUT_CLAMPED" in warning for warning in warnings)


def test_threshold_alias_used_when_primary_missing() -> None:
    """در نبود COV_MIN از COV_MIN_PERCENT استفاده می‌شود."""

    threshold, warnings = coverage_gate._resolve_threshold(None, "97")
    assert threshold == 97.0
    assert warnings == []


def test_stream_collector_limits_tail_and_capture() -> None:
    """بافر جریان باید خطوط پایانی را محدود و درصد پوشش را استخراج کند."""

    collector = coverage_gate.StreamCollector(
        tail_limit=5,
        capture_char_limit=120,
        echo_stdout=False,
        echo_stderr=False,
    )
    for index in range(12):
        collector.consume(f"TOTAL 1 1 {index}%\n", "stdout")
    snapshot = collector.snapshot()
    assert len(snapshot.tail_lines) == 5
    assert snapshot.text_coverage_percent == 11.0
    assert len(snapshot.stdout) <= 120


def test_stream_collector_truncates_large_output() -> None:
    """ورودی بسیار بزرگ نباید باعث رشد نامحدود حافظه شود."""

    collector = coverage_gate.StreamCollector(
        tail_limit=10,
        capture_char_limit=500,
        echo_stdout=False,
        echo_stderr=False,
    )
    bulk = "\n".join(f"line-{i}" for i in range(55_000)) + "\n"
    collector.consume(bulk, "stdout")
    snapshot = collector.snapshot()
    assert len(snapshot.tail_lines) == 10
    assert len(snapshot.stdout) <= 500


def test_resolve_coverage_prefers_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """در صورت وجود XML مقدار خط-rate باید مبنا قرار گیرد."""

    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text("<coverage line-rate=\"0.953\" />", encoding="utf-8")
    run = coverage_gate.PytestRun(
        returncode=0,
        stdout="",
        stderr="",
        tail_lines=(),
        summary_candidates=(),
        coverage_failure=None,
        text_coverage_percent=87.0,
    )
    monkeypatch.setattr(coverage_gate, "COVERAGE_XML", xml_path)
    assert coverage_gate._resolve_coverage_percent(run) == pytest.approx(95.3)


def test_resolve_coverage_falls_back_to_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """در نبود XML باید از مقدار متنی استفاده شود."""

    missing_xml = tmp_path / "missing.xml"
    run = coverage_gate.PytestRun(
        returncode=0,
        stdout="",
        stderr="",
        tail_lines=(),
        summary_candidates=(),
        coverage_failure=None,
        text_coverage_percent=82.5,
    )
    monkeypatch.setattr(coverage_gate, "COVERAGE_XML", missing_xml)
    assert coverage_gate._resolve_coverage_percent(run) == pytest.approx(82.5)


def test_missing_pytest_cov_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """نبود pytest-cov باید پیام فارسی و خروج با کد ۶ را به‌دنبال داشته باشد."""

    original_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name == "pytest_cov":  # pragma: no cover - مسیر تست سفارشی
            raise ImportError("simulated missing plugin")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as exc:
        coverage_gate._ensure_pytest_cov()
    assert exc.value.code == 6
    captured = capsys.readouterr()
    assert "PYTEST_COV_MISSING" in captured.err


@pytest.mark.integration
def test_gate_summary_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """اجرای موفق باید با خلاصهٔ فارسی و نماد ✅ پایان یابد."""

    env = {
        "COV_MIN": "0",
        "LEGACY_TEST_PATTERN": "tests/security/test_coverage_gate_parser.py",
    }
    result = _run_gate(env)
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines[-1].startswith("✅ پوشش تست‌ها عبور کرد")


@pytest.mark.integration
def test_gate_summary_failure_with_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """آستانهٔ بزرگ باید هشدار clamp و خطای فارسی تولید کند."""

    env = {
        "COV_MIN": "150",
        "LEGACY_TEST_PATTERN": "tests/security/test_coverage_gate_parser.py",
    }
    result = _run_gate(env)
    assert result.returncode != 0
    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert any("COV_INVALID_INPUT_CLAMPED" in line for line in stdout_lines[:-1])
    assert stdout_lines[-1].startswith("❌ COV_BELOW_THRESHOLD")

