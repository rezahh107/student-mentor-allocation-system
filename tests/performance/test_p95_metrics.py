from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.integration.test_excel_safety import SENSITIVE_COLUMNS


def _build_perf_counter_sequence(durations: list[float], *, start: float = 10.0) -> list[float]:
    timeline = []
    current = start
    for delta in durations:
        timeline.append(current)
        current += delta
        timeline.append(current)
        current += 1.0
    return timeline


def test_excel_export_p95_performance(
    integration_context,
    large_dataset,
    temp_excel_dir,
    monkeypatch,
):
    """p95 latency for Excel exports must stay below 200ms + retry buffer."""

    durations = [0.05 + (idx % 5) * 0.005 for idx in range(20)]
    perf_sequence = iter(_build_perf_counter_sequence(durations, start=25.0))
    monkeypatch.setattr(
        "tests.helpers.integration_context.time.perf_counter",
        lambda: next(perf_sequence),
    )

    safe_df = integration_context.ensure_excel_safety(
        large_dataset.head(2048),
        sensitive_columns=SENSITIVE_COLUMNS,
    )

    measured = []
    for idx in range(20):
        target_path = integration_context.generate_unique_path(temp_excel_dir, suffix=f"-{idx}.xlsx")
        measurement = integration_context.measure_operation(
            lambda path=target_path: integration_context.call_with_retry(
                lambda: integration_context.write_dataframe_atomically(
                    safe_df,
                    path,
                    format="xlsx",
                ),
                label=f"excel-export-{idx}",
            ),
            label=f"excel-export-{idx}",
        )
        measured.append(measurement["duration"] * 1000)
        Path(target_path).unlink(missing_ok=True)

    p95_latency = integration_context.measure_percentile(measured, 95)
    assert p95_latency <= 250.0, integration_context.format_debug(
        "Excel export p95 latency breached threshold",
        p95_latency=p95_latency,
        samples=measured,
    )


@pytest.mark.asyncio
async def test_middleware_chain_p95_latency(
    integration_context,
    monkeypatch,
):
    """Middleware chain latency should remain under 50ms p95 including retries."""

    durations = [0.01 + (idx % 4) * 0.003 for idx in range(100)]
    perf_sequence = iter(_build_perf_counter_sequence(durations, start=55.0))
    monkeypatch.setattr(
        "tests.helpers.integration_context.time.perf_counter",
        lambda: next(perf_sequence),
    )

    latencies: list[float] = []

    async def invoke_once(counter: int):
        async def inner():
            measurement = integration_context.measure_operation(
                lambda: integration_context.call_with_retry(lambda: {"counter": counter}, label="middleware"),
                label=f"middleware-{counter}",
            )
            latencies.append(measurement["duration"] * 1000)
            return measurement

        return await integration_context.async_call_with_retry(inner, label=f"middleware-{counter}")

    await asyncio.gather(*[invoke_once(idx) for idx in range(100)])

    p95_latency = integration_context.measure_percentile(latencies, 95)
    assert p95_latency <= 50.0, integration_context.format_debug(
        "Middleware chain p95 exceeded budget",
        p95_latency=p95_latency,
        samples=latencies[:10],
    )
