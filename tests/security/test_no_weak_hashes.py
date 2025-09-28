"""Regression guard ensuring insecure hash algorithms never ship."""
from __future__ import annotations

from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from scripts import security_tools
from scripts import check_no_weak_hashes
from scripts.check_no_weak_hashes import PROJECT_ROOT, scan_for_weak_hashes


def test_no_weak_hash_algorithms(tmp_path: Path) -> None:
    findings = scan_for_weak_hashes()
    assert not findings, "ضعف رمزنگاری شناسایی شد: " + ", ".join(
        f"{item.path.relative_to(PROJECT_ROOT)}:{item.line_number}" for item in findings
    )


def test_custom_path_override(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import hashlib\nhashlib.md5(b'0')\n", encoding="utf-8")
    findings = scan_for_weak_hashes([sample])
    assert findings and findings[0].path == sample


def test_scanner_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []
    registry = CollectorRegistry()

    def _flaky(_: list[Path]) -> list[check_no_weak_hashes.Finding]:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("fs busy")
        return []

    monkeypatch.setattr(check_no_weak_hashes, "scan_for_weak_hashes", _flaky)
    monkeypatch.setattr(check_no_weak_hashes, "_RETRY_REGISTRY", registry)
    monkeypatch.setattr(check_no_weak_hashes, "_SLEEPER", lambda _: None)
    monkeypatch.setenv("SEC_WEAK_HASH_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("SEC_WEAK_HASH_BASE_DELAY", "0")
    monkeypatch.setenv("SEC_WEAK_HASH_JITTER", "0")

    exit_code = check_no_weak_hashes.main([])
    assert exit_code == 0
    assert len(attempts) == 2
    attempts_metric = registry.get_sample_value(
        "security_tool_retry_attempts_total", labels={"tool": "weak_hash_scan"}
    )
    assert attempts_metric == 2.0
    security_tools.reset_metrics(registry=registry)
