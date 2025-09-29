from __future__ import annotations

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "M" * 32, "role": "MANAGER", "center": 303},
    {"value": "R" * 32, "role": "METRICS_RO", "metrics_only": True},
]

SIGNING_KEYS = [
    {"kid": "KP95", "secret": "S" * 48, "state": "active"},
]


def _extract_histogram_bucket(samples, *, suffix: str, labels: dict[str, str]) -> float:
    for sample in samples:
        if not sample.name.endswith(suffix):
            continue
        if all(sample.labels.get(key) == value for key, value in labels.items()):
            return sample.value
    raise AssertionError(f"missing histogram sample {suffix} with {labels}")


def test_p95_under_budget(monkeypatch) -> None:
    durations = [0.05] * 600
    with access_test_app(
        monkeypatch,
        tokens=TOKENS,
        signing_keys=SIGNING_KEYS,
        timer_durations=durations,
        metrics_namespace="auth-p95",
    ) as ctx:
        admin_token = TOKENS[0]["value"]
        metrics_token = TOKENS[2]["value"]
        for idx in range(20):
            response = ctx.client.post(
                "/api/jobs",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Idempotency-Key": f"idem-{idx:04d}",
                    "X-Client-ID": f"client-{idx:02d}",
                },
            )
            assert response.status_code == 200

        for idx in range(5):
            metrics_resp = ctx.client.get(
                "/metrics",
                headers={"Authorization": f"Bearer {metrics_token}"},
            )
            assert metrics_resp.status_code == 200

        auth_hist = ctx.metrics.middleware.auth_latency_seconds.collect()[0].samples
        total = _extract_histogram_bucket(auth_hist, suffix="_count", labels={})
        bucket_le_0_1 = _extract_histogram_bucket(
            auth_hist,
            suffix="_bucket",
            labels={"le": "0.1"},
        )
        assert bucket_le_0_1 >= 0.95 * total

        request_hist = ctx.metrics.request_latency.collect()[0].samples
        request_total = _extract_histogram_bucket(request_hist, suffix="_count", labels={})
        request_le_0_2 = _extract_histogram_bucket(
            request_hist,
            suffix="_bucket",
            labels={"le": "0.2"},
        )
        assert request_le_0_2 == request_total

        ctx.metrics.reset()

