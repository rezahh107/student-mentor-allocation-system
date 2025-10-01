from __future__ import annotations

import warnings

import pytest

from tests.hardened_api.conftest import assert_clean_final_state, setup_test_data


def test_asyncio_mode_is_auto(pytestconfig: pytest.Config) -> None:
    """Ensure pytest-asyncio operates under the configured auto mode."""
    assert pytestconfig.getini("asyncio_mode") == "auto"


@pytest.mark.asyncio
async def test_httpx_requests_emit_no_deprecation_warnings(clean_state, client):
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "Idempotency-Key": "HTTPXWARNCHECK001",
        "X-Request-ID": "warn-check-req",
    }
    payload = setup_test_data(unique_suffix="77")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        response = await client.post("/allocations", json=payload, headers=headers)
        assert response.status_code == 200, response.text

        status_headers = {"Authorization": "Bearer TESTTOKEN1234567890"}
        status_response = await client.get("/status", headers=status_headers)
        assert status_response.status_code == 200, status_response.text

        error_headers = headers | {
            "Content-Type": "application/xml",
            "Idempotency-Key": "HTTPXWARNERR0002",
        }
        error_response = await client.post(
            "/allocations",
            content="{}",
            headers=error_headers,
        )
        assert error_response.status_code == 415, error_response.text
    httpx_warnings = [warning for warning in captured if "httpx" in str(warning.message).lower()]
    assert not httpx_warnings
    await assert_clean_final_state(client)
