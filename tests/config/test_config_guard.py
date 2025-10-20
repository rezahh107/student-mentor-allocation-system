from __future__ import annotations

import pytest
from pydantic import ValidationError

from sma.ops.config import OpsSettings, SLOThresholds


def test_forbid_unknown_keys():
    settings = OpsSettings(
        reporting_replica_dsn="postgresql://user:pass@localhost:5432/replica",
        metrics_read_token="metrics-token-123456",
        slo_thresholds=SLOThresholds(
            healthz_p95_ms=120,
            readyz_p95_ms=150,
            export_p95_ms=800,
            export_error_budget=42,
        ),
    )
    assert settings.metrics_read_token.startswith("metrics")

    with pytest.raises(ValidationError):
        OpsSettings(
            reporting_replica_dsn="postgresql://user:pass@localhost:5432/replica",
            metrics_read_token="metrics-token-123456",
            slo_thresholds=SLOThresholds(
                healthz_p95_ms=120,
                readyz_p95_ms=150,
                export_p95_ms=800,
                export_error_budget=42,
            ),
            unknown="oops",  # type: ignore[arg-type]
        )
