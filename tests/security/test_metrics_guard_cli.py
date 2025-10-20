from __future__ import annotations

from uuid import uuid4

from sma.tools import cli as cli_module


def test_metrics_endpoint_requires_token() -> None:
    namespace = f"metrics-{uuid4().hex}"
    with cli_module._build_test_app(namespace) as client:
        forbidden = client.get("/metrics")
        assert forbidden.status_code in {
            401,
            403,
        }, f"Context: status={forbidden.status_code} body={forbidden.text}"

        headers = {"X-Metrics-Token": cli_module.DEFAULT_TOKENS[1]["value"]}
        allowed = client.get("/metrics", headers=headers)
        assert allowed.status_code == 200, (
            "Context: status={status} body={body}".format(
                status=allowed.status_code, body=allowed.text[:200]
            )
        )
        assert "retry_attempts_total" in allowed.text, f"Context: body={allowed.text}"
