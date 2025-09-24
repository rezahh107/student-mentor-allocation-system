"""آزمون‌های دود و انتهابه‌انتها با ملاحظات Hypothesis و سنجش p95."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

HYPOTHESIS_REASON = "hypothesis نصب نیست (محلی)"

try:
    hypothesis = pytest.importorskip("hypothesis", reason=HYPOTHESIS_REASON)
    strategies = pytest.importorskip("hypothesis.strategies", reason=HYPOTHESIS_REASON)
except pytest.skip.Exception:
    hypothesis = None
    strategies = None


@pytest.mark.smoke
@pytest.mark.e2e
def test_smoke_file_roundtrip(tmp_path: Path) -> None:
    """ساده‌ترین مسیر دود بدون نیاز به وابستگی‌های جانبی را اعتبارسنجی می‌کند."""

    sample_path = tmp_path / "smoke.txt"
    sample_path.write_text("ready\n", encoding="utf-8")
    assert sample_path.read_text(encoding="utf-8").strip() == "ready"


@pytest.mark.smoke
@pytest.mark.e2e
def test_json_roundtrip_property_hypothesis_required(tmp_path: Path) -> None:
    """تست مبتنی بر Hypothesis که در صورت نیاز سنجش p95 را نیز اعمال می‌کند."""

    if hypothesis is None or strategies is None:
        pytest.skip(HYPOTHESIS_REASON)

    durations: list[float] = []

    @hypothesis.given(strategies.text(max_size=32))
    def _roundtrip(payload: str) -> None:
        start = time.perf_counter()
        envelope = {"payload": payload}
        artifact = tmp_path / "payload.json"
        artifact.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        loaded = json.loads(artifact.read_text(encoding="utf-8"))
        durations.append((time.perf_counter() - start) * 1000.0)
        assert loaded == envelope

    _roundtrip()

    if os.getenv("RUN_P95_CHECK") == "1" and durations:
        raw_limit = os.getenv("P95_MS_ALLOCATIONS", "200")
        stripped = raw_limit.strip()
        try:
            limit = int(stripped or "200")
        except ValueError:
            limit = 200
        ordered = sorted(durations)
        index = max(int(len(ordered) * 0.95) - 1, 0)
        measured_p95_ms = ordered[index]
        assert (
            measured_p95_ms <= limit
        ), f"p95 اندازه‌گیری‌شده {measured_p95_ms:.1f} میلی‌ثانیه بود و از حد {limit} عبور کرد."
