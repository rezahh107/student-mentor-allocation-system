from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

import pytest
from unittest.mock import patch

from scripts.ci_no_pii_scan import (
    Finding,
    atomic_write_report,
    coerce_to_text,
    compute_repo_salt,
    iter_sensitive_tokens,
    mask_secret,
    scan_repository,
)


@pytest.fixture
def pii_scan_sandbox(tmp_path, monkeypatch):
    unique_root = tmp_path / f"repo_{uuid4().hex}"
    (unique_root / "scripts").mkdir(parents=True)
    (unique_root / "reports").mkdir()
    monkeypatch.chdir(unique_root)
    yield unique_root
    report_path = unique_root / "reports" / "pii-scan.json"
    if report_path.exists():
        report_path.unlink()


def _retry_with_backoff(operation: Callable[[], Optional[list[Finding]]], *, seed: str) -> list[Finding]:
    base_delay = 0.01
    rng = random.Random(seed)
    last_error: Optional[AssertionError] = None
    for attempt in range(1, 4):
        try:
            result = operation()
            if result is None:
                raise AssertionError("عملیات نتیجه‌ای بازنگرداند.")
            return result
        except AssertionError as exc:  # pragma: no cover - مسیر خطا فقط در شکست تست
            last_error = exc
            jitter = rng.random() * 0.005
            time.sleep(base_delay * (2 ** (attempt - 1)) + jitter)
    if last_error is not None:
        raise last_error
    raise AssertionError("بازگشت بدون نتیجه")


def _debug_context(root: Path) -> str:
    return json.dumps(
        {
            "cwd": os.getcwd(),
            "files": sorted(str(p) for p in root.rglob("*")),
            "timestamp": 1234567890,
        },
        ensure_ascii=False,
    )


@pytest.mark.usefixtures("pii_scan_sandbox")
def test_pii_scan_handles_edge_inputs_without_leaking(pii_scan_sandbox: Path) -> None:
    sandbox_root = pii_scan_sandbox
    logs_dir = sandbox_root / "logs"
    logs_dir.mkdir()
    sample_log = logs_dir / f"sample_{uuid4().hex}.log"
    long_text = "الف" * 100_000
    zero_width_mobile = "\u200c۰۹۱۲۳۴۵۶۷۸۹"
    persian_mobile = "۰۹۱۲۳۴۵۶۷۸۹"
    national_id = "1234567890"
    sample_log.write_text(
        "\n".join(
            [
                coerce_to_text(None),
                coerce_to_text(0),
                coerce_to_text("0"),
                long_text,
                zero_width_mobile,
                persian_mobile,
                national_id,
            ]
        ),
        encoding="utf-8",
    )

    massive_file = logs_dir / f"massive_{uuid4().hex}.txt"
    massive_file.write_text("الف" * 1_000_000, encoding="utf-8")

    def operation() -> list[Finding]:
        findings = scan_repository(
            sandbox_root,
            [
                sample_log.relative_to(sandbox_root),
                massive_file.relative_to(sandbox_root),
            ],
        )
        atomic_write_report(sandbox_root, findings)
        return findings

    with patch("time.time", return_value=1711111111.0), patch("time.sleep", lambda *_: None):
        findings = _retry_with_backoff(operation, seed="pii-scan")

    context = _debug_context(sandbox_root)

    evidence_mobile = [f for f in findings if f.kind == "mobile"]
    evidence_national = [f for f in findings if f.kind == "national_id"]

    assert evidence_mobile, f"موبایل شناسایی نشد: {context}"
    assert evidence_national, f"کدملی شناسایی نشد: {context}"

    for finding in findings:
        assert len(finding.masked) == 32, f"طول ماسک اشتباه است: {context}"
        assert finding.masked.isalnum(), f"حروف ماسک معتبر نیست: {context}"

    report_path = sandbox_root / "reports" / "pii-scan.json"
    with report_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["findings"], f"گزارش خالی است: {context}"
    for entry in payload["findings"]:
        assert "masked" in entry, f"کلید ماسک وجود ندارد: {context}"
        assert entry["masked"] not in {persian_mobile, national_id}, f"افشای داده رخ داد: {context}"

    for value in (None, 0, "0", "", "۰۱۲۳", "٠٩١٢٣٤٥٦٧٨٩"):
        coerced = coerce_to_text(value)
        tokens = list(iter_sensitive_tokens(coerced))
        assert all(token[1] != coerced for token in tokens), f"ورودی ساده نباید افشا شود: {context}"

    salt = compute_repo_salt(sandbox_root)
    expected_mask = mask_secret("09123456789", sandbox_root)
    assert expected_mask == mask_secret("۰۹۱۲۳۴۵۶۷۸۹", sandbox_root), f"نرمال‌سازی موبایل نادرست است: {context}"
    assert salt == compute_repo_salt(sandbox_root), f"نمک باید دترمینیستیک باشد: {context}"
