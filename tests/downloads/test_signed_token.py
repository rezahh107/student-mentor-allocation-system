from __future__ import annotations

from urllib.parse import quote

import pytest

from tests.downloads.conftest import build_token, write_artifact


def test_expired_token_uses_injected_clock(download_env) -> None:
    env = download_env
    filename = "report.csv"
    content = b"id,name\r\n1,Ali\r\n"
    digest = write_artifact(env.workspace, filename, content)
    token = build_token(env=env, filename=filename, sha256=digest, size=len(content), expires_in=-5)

    response = env.client.get(f"/download/{token}")
    payload = response.json()
    assert response.status_code == 403, payload
    assert payload["fa_error_envelope"]["message"] == "توکن دانلود نامعتبر یا منقضی است.", payload

    invalid_samples = env.metrics.invalid_token_total.collect()[0].samples
    invalid_value = next(sample.value for sample in invalid_samples if sample.name.endswith("_total"))
    assert invalid_value == 1, invalid_samples
    request_samples = {
        sample.labels["status"]: sample.value
        for sample in env.metrics.requests_total.collect()[0].samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert request_samples.get("invalid_token") == 1, request_samples


@pytest.mark.parametrize("raw_token", ["0", " ", "\u200c", "a" * 2048, "۰۱۲۳۴"])
def test_invalid_tokens_return_persian_error(download_env, raw_token: str) -> None:
    env = download_env
    encoded = quote(raw_token, safe="")
    response = env.client.get(f"/download/{encoded}")
    payload = response.json()
    assert response.status_code == 403, payload
    assert payload["fa_error_envelope"]["message"] == "توکن دانلود نامعتبر یا منقضی است.", payload
    invalid_value = next(
        sample.value
        for sample in env.metrics.invalid_token_total.collect()[0].samples
        if sample.name.endswith("_total")
    )
    assert invalid_value >= 1


def test_manifest_mismatch_returns_not_found(download_env, monkeypatch) -> None:
    env = download_env
    filename = "integrity.csv"
    content = b"a,b\r\n1,2\r\n"
    digest = write_artifact(env.workspace, filename, content)
    # Corrupt manifest digest deterministically
    manifest_path = env.workspace / "export_manifest.json"
    manifest_payload = manifest_path.read_text(encoding="utf-8").replace(digest, "0" * len(digest))
    manifest_path.write_text(manifest_payload, encoding="utf-8")
    token = build_token(env=env, filename=filename, sha256=digest, size=len(content))

    response = env.client.get(f"/download/{token}")
    payload = response.json()
    assert response.status_code == 404, payload
    assert payload["fa_error_envelope"]["message"] == "شیء درخواستی یافت نشد.", payload
    samples = env.metrics.requests_total.collect()[0].samples
    status_map = {
        sample.labels["status"]: sample.value
        for sample in samples
        if "status" in sample.labels and sample.name.endswith("_total")
    }
    assert status_map.get("not_found") == 1, status_map
    not_found_value = next(
        sample.value
        for sample in env.metrics.not_found_total.collect()[0].samples
        if sample.name.endswith("_total")
    )
    assert not_found_value == 1


def test_path_traversal_token_rejected(download_env) -> None:
    env = download_env
    token = build_token(
        env=env,
        filename="../secret.csv",
        sha256="0" * 64,
        size=1,
    )
    response = env.client.get(f"/download/{token}")
    payload = response.json()
    assert response.status_code == 403, payload
    assert payload["fa_error_envelope"]["message"] == "توکن دانلود نامعتبر یا منقضی است.", payload
