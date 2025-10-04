from __future__ import annotations

import asyncio
from typing import Iterable

import httpx
import pytest

from tests.downloads.conftest import build_token, write_artifact


pytest_plugins = ("pytest_asyncio.plugin",)


def _collect(counter, label: str | None = None) -> dict[str, float]:
    samples: dict[str, float] = {}
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            if label is None:
                samples[sample.name] = sample.value
            elif label in sample.labels:
                samples[sample.labels[label]] = sample.value
    return samples


@pytest.mark.asyncio
async def test_parallel_downloads_metrics_stable(download_env) -> None:
    env = download_env
    filename = "stress.bin"
    payload = (b"0123456789abcdef" * 8192) + b"end"
    digest = write_artifact(env.workspace, filename, payload)
    token = build_token(env=env, filename=filename, sha256=digest, size=len(payload))
    url = f"/download/{token}"

    range_pairs: Iterable[tuple[int, int]] = (
        (0, 1023),
        (2048, 4095),
        (len(payload) - 2048, len(payload) - 1),
    )

    async with httpx.AsyncClient(app=env.app, base_url="http://testserver") as client:
        async def _fetch(headers: dict[str, str]):
            response = await client.get(url, headers=headers)
            return response

        tasks = [
            asyncio.create_task(_fetch({"X-Request-ID": f"full-{idx}"}))
            for idx in range(4)
        ]
        tasks.extend(
            asyncio.create_task(
                _fetch({"Range": f"bytes={start}-{end}", "X-Request-ID": f"range-{idx}"})
            )
            for idx, (start, end) in enumerate(range_pairs)
        )
        tasks.append(
            asyncio.create_task(
                _fetch({"Range": "bytes=50-10", "X-Request-ID": "invalid-range"})
            )
        )
        tasks.append(
            asyncio.create_task(
                _fetch({"If-None-Match": f'"{digest}"', "X-Request-ID": "cached"})
            )
        )

        responses = await asyncio.gather(*tasks)

    successes = [resp for resp in responses if resp.status_code == 200]
    partials = [resp for resp in responses if resp.status_code == 206]
    invalid = [resp for resp in responses if resp.status_code == 416]
    cached = [resp for resp in responses if resp.status_code == 304]

    assert len(successes) == 4
    assert len(partials) == 3
    assert len(invalid) == 1
    assert len(cached) == 1

    served_bytes = sum(len(resp.content) for resp in successes + partials)

    request_metrics = _collect(env.metrics.requests_total, "status")
    range_metrics = _collect(env.metrics.range_requests_total, "status")
    byte_total = _collect(env.metrics.bytes_total)
    retry_metrics = _collect(env.metrics.retry_total, "outcome")
    exhaustion_metrics = _collect(env.metrics.retry_exhaustion_total)

    debug_context = {
        "namespace": env.namespace,
        "workspace": str(env.workspace),
        "requests": request_metrics,
        "ranges": range_metrics,
    }

    assert request_metrics.get("success") == len(successes), debug_context
    assert request_metrics.get("partial") == len(partials), debug_context
    assert request_metrics.get("invalid_range") == len(invalid), debug_context
    assert request_metrics.get("not_modified") == len(cached), debug_context

    assert range_metrics.get("accepted") == len(partials), debug_context
    assert range_metrics.get("rejected") == len(invalid), debug_context
    assert range_metrics.get("absent") == len(successes), debug_context

    total_bytes_value = next(iter(byte_total.values())) if byte_total else 0
    assert total_bytes_value == served_bytes, (byte_total, served_bytes, debug_context)

    assert not retry_metrics, retry_metrics
    exhaustion_value = next(iter(exhaustion_metrics.values())) if exhaustion_metrics else 0
    assert exhaustion_value == 0, exhaustion_metrics
