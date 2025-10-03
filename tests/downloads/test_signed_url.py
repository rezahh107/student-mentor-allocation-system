from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.obs.metrics import build_metrics
from src.phase6_import_to_sabt.security.signer import (
    DualKeySigner,
    SignatureError,
    SigningKeyDefinition,
    SigningKeySet,
)


def test_dual_key_acceptance_and_ttl() -> None:
    registry = CollectorRegistry()
    metrics = build_metrics("download_security", registry=registry)
    clock = FixedClock(datetime(2024, 1, 1, 0, 0, tzinfo=ZoneInfo("Asia/Tehran")))
    keys = SigningKeySet(
        [
            SigningKeyDefinition("ACTV", "a" * 48, "active"),
            SigningKeyDefinition("NEXT", "b" * 48, "next"),
        ]
    )
    signer = DualKeySigner(keys=keys, clock=clock, metrics=metrics, default_ttl_seconds=120)

    components = signer.issue("exports/report.xlsx", ttl_seconds=120)
    assert signer.verify_components(
        signed=components.signed,
        kid=components.kid,
        exp=components.exp,
        sig=components.sig,
        now=clock.now(),
    ) == "exports/report.xlsx"

    canonical = signer._canonical("GET", components.path, {}, components.exp)
    next_key = keys.get("NEXT")
    forged = signer._sign(next_key.secret, canonical)
    assert signer.verify_components(
        signed=components.signed,
        kid=next_key.kid,
        exp=components.exp,
        sig=forged,
        now=clock.now(),
    ) == "exports/report.xlsx"

    expired_exp = int((clock.now() - timedelta(seconds=1)).timestamp())
    with pytest.raises(SignatureError) as expired:
        signer.verify_components(
            signed=components.signed,
            kid=components.kid,
            exp=expired_exp,
            sig=components.sig,
            now=clock.now(),
        )
    assert expired.value.message_fa == "لینک دانلود منقضی شده است."

    with pytest.raises(SignatureError) as unknown:
        signer.verify_components(
            signed=components.signed,
            kid="ZZZZ",
            exp=components.exp,
            sig=components.sig,
            now=clock.now(),
        )
    assert unknown.value.message_fa == "کلید امضا ناشناخته است."

    outcomes = {sample.labels["outcome"] for sample in metrics.download_signed_total.collect()[0].samples}
    assert {"issued", "ok", "expired", "unknown_kid"}.issubset(outcomes)
