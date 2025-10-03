from __future__ import annotations

import pytest

from tests.downloads.conftest import build_token, write_artifact


def test_part_file_never_served(download_env) -> None:
    env = download_env
    filename = "pending.csv"
    payload = b"a,b\r\n1,2\r\n"
    digest = write_artifact(env.workspace, filename, payload)
    part_path = env.workspace / f"{filename}.part"
    part_path.write_bytes(b"intermediate")

    token = build_token(env=env, filename=filename, sha256=digest, size=len(payload))
    response = env.client.get(f"/download/{token}")
    payload_resp = response.json()
    assert response.status_code == 409, payload_resp
    assert payload_resp["fa_error_envelope"]["message"] == "فایل در حال نهایی‌سازی است؛ بعداً تلاش کنید.", payload_resp

    samples = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert samples.get("in_progress") == 1, samples
    part_path.unlink()
