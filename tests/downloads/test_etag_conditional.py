from __future__ import annotations

import pytest

from tests.downloads.conftest import build_token, write_artifact


def test_if_none_match_304(download_env) -> None:
    env = download_env
    filename = "students.csv"
    payload = b"id,name\r\n1,Ali\r\n"
    digest = write_artifact(env.workspace, filename, payload)
    token = build_token(env=env, filename=filename, sha256=digest, size=len(payload))

    first = env.client.get(
        f"/download/{token}",
        headers={"X-Request-ID": "req-etag"},
    )
    assert first.status_code == 200, first.text
    assert first.headers["ETag"] == f'"{digest}"'
    assert first.headers["Content-Disposition"].startswith("attachment;"), first.headers
    assert first.content == payload

    second = env.client.get(
        f"/download/{token}",
        headers={"If-None-Match": first.headers["ETag"]},
    )
    assert second.status_code == 304, second.text
    assert second.headers["ETag"] == first.headers["ETag"]
    assert second.content == b""

    request_samples = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert request_samples.get("success") == 1, request_samples
    assert request_samples.get("not_modified") == 1, request_samples
    byte_samples = env.metrics.bytes_total.collect()[0].samples
    byte_value = next(sample.value for sample in byte_samples if sample.name.endswith("_total"))
    assert byte_value == len(payload)
    range_samples = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.range_requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    # Only the successful 200 response reaches the range accounting; the 304 short-circuits
    # before range evaluation so it should not increment the "absent" bucket again.
    assert range_samples.get("absent") == 1, range_samples
