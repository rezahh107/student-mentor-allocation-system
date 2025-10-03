from __future__ import annotations

import pytest

from tests.downloads.conftest import build_token, write_artifact


def test_valid_single_range_206(download_env) -> None:
    env = download_env
    filename = "range.csv"
    payload = b"0123456789"
    digest = write_artifact(env.workspace, filename, payload)
    token = build_token(env=env, filename=filename, sha256=digest, size=len(payload))

    response = env.client.get(
        f"/download/{token}",
        headers={"Range": "bytes=2-5"},
    )
    assert response.status_code == 206, response.text
    assert response.headers["Content-Range"] == "bytes 2-5/10"
    assert response.headers["Content-Length"] == "4"
    assert response.content == payload[2:6]

    requests = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert requests.get("partial") == 1, requests
    ranges = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.range_requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert ranges.get("accepted") == 1, ranges
    bytes_samples = env.metrics.bytes_total.collect()[0].samples
    bytes_value = next(sample.value for sample in bytes_samples if sample.name.endswith("_total"))
    assert bytes_value == 4


def test_invalid_multi_range_rejected(download_env) -> None:
    env = download_env
    filename = "invalid.csv"
    payload = b"abcdefghij"
    digest = write_artifact(env.workspace, filename, payload)
    token = build_token(env=env, filename=filename, sha256=digest, size=len(payload))

    response = env.client.get(
        f"/download/{token}",
        headers={"Range": "bytes=0-1,2-3"},
    )
    body = response.json()
    assert response.status_code == 416, body
    assert body["fa_error_envelope"]["message"] == "درخواست محدوده نامعتبر است.", body

    ranges = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.range_requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert ranges.get("rejected") == 1, ranges
    requests = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert requests.get("invalid_range") == 1, requests
