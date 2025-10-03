from __future__ import annotations

import argparse
import json
from datetime import datetime

from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.obs.metrics import build_metrics
from src.phase6_import_to_sabt.security.config import AccessConfigGuard
from src.phase6_import_to_sabt.security.rotation_cli import _cmd_generate, _cmd_promote
from src.phase6_import_to_sabt.security.signer import DualKeySigner, SigningKeySet


TOKENS_ENV = "ROTATION_TOKENS"
KEYS_ENV = "ROTATION_KEYS"


def test_accepts_active_and_next(monkeypatch, capsys) -> None:
    tokens_payload = [
        {"value": "R" * 32, "role": "ADMIN"},
    ]
    keys_payload = [
        {"kid": "ACTV", "secret": "a" * 48, "state": "active"},
        {"kid": "NEXT", "secret": "b" * 48, "state": "next"},
    ]
    monkeypatch.setenv(TOKENS_ENV, json.dumps(tokens_payload))
    monkeypatch.setenv(KEYS_ENV, json.dumps(keys_payload))

    guard = AccessConfigGuard()
    settings = guard.load(tokens_env=TOKENS_ENV, signing_keys_env=KEYS_ENV, download_ttl_seconds=300)
    assert settings.next_kid == "NEXT"

    registry = CollectorRegistry()
    metrics = build_metrics("rotation_ops", registry=registry)
    clock = FixedClock(datetime(2024, 1, 1, 0, 0, tzinfo=ZoneInfo("Asia/Tehran")))
    signer = DualKeySigner(
        keys=SigningKeySet(settings.signing_keys),
        clock=clock,
        metrics=metrics,
        default_ttl_seconds=settings.download_ttl_seconds,
    )

    issued = signer.issue("exports/summary.xlsx", ttl_seconds=120)
    verified = signer.verify_components(
        signed=issued.signed,
        kid=issued.kid,
        exp=issued.exp,
        sig=issued.sig,
        now=clock.now(),
    )
    assert verified == "exports/summary.xlsx"

    next_key = next(item for item in settings.signing_keys if item.state == "next")
    forged = signer._sign(next_key.secret, signer._canonical("GET", issued.path, {}, issued.exp))
    verified_next = signer.verify_components(
        signed=issued.signed,
        kid=next_key.kid,
        exp=issued.exp,
        sig=forged,
        now=clock.now(),
    )
    assert verified_next == "exports/summary.xlsx"

    args_promote = argparse.Namespace(
        tokens_env=TOKENS_ENV,
        signing_keys_env=KEYS_ENV,
        ttl=300,
        kid="NEXT",
        metrics=metrics,
    )
    capsys.readouterr()
    _cmd_promote(args_promote)
    promoted = json.loads(capsys.readouterr().out)
    assert promoted["event"] == "promote"
    promote_metric = registry.get_sample_value(
        "rotation_ops_token_rotation_total",
        labels={"event": "promote"},
    )
    assert promote_metric == 1.0

    args_generate = argparse.Namespace(
        tokens_env=TOKENS_ENV,
        signing_keys_env=KEYS_ENV,
        ttl=300,
        kid="NEW1",
        seed="seed-value",
        metrics=metrics,
    )
    _cmd_generate(args_generate)
    generated = json.loads(capsys.readouterr().out)
    assert generated["event"] == "generate"
    assert generated["next_kid"] == "NEW1"
    generate_metric = registry.get_sample_value(
        "rotation_ops_token_rotation_total",
        labels={"event": "generate"},
    )
    assert generate_metric == 1.0

    metrics.reset()

