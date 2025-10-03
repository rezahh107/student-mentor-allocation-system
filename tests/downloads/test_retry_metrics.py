from __future__ import annotations

from pathlib import Path

import pytest

from tests.downloads.conftest import build_token, write_artifact


def test_retry_records_metrics(download_env, monkeypatch) -> None:
    env = download_env
    filename = "retry.csv"
    payload = b"retry,case\r\n1,ok\r\n"
    digest = write_artifact(env.workspace, filename, payload)
    token = build_token(env=env, filename=filename, sha256=digest, size=len(payload))
    target = env.workspace / filename

    attempts: dict[str, int] = {"count": 0}
    original_open = Path.open

    def _flaky_open(path_self: Path, mode: str = "r", *args, **kwargs):  # type: ignore[override]
        if path_self == target and "b" in mode and attempts["count"] == 0:
            attempts["count"] += 1
            raise OSError("transient failure")
        return original_open(path_self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _flaky_open)

    response = env.client.get(f"/download/{token}")
    assert response.status_code == 200, response.text
    assert response.content == payload
    assert attempts["count"] == 1

    retry_samples = {
        sample.labels["outcome"]: sample.value
        for sample in env.metrics.retry_total.collect()[0].samples
        if "outcome" in sample.labels and sample.name.endswith("_total")
    }
    assert retry_samples.get("retry") == 1, retry_samples
    assert retry_samples.get("success") == 1, retry_samples
