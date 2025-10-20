# -*- coding: utf-8 -*-
"""Configuration loader for the counter service."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

DEFAULT_METRICS_PORT = 9108
SUPPORTED_ENVS = {"dev", "stage", "prod"}


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """Typed configuration block for the counter service."""

    db_url: str
    pii_hash_salt: str
    metrics_port: int
    env: Literal["dev", "stage", "prod"]


def load_from_env() -> ServiceConfig:
    """Read configuration from environment variables with validation."""

    db_url = os.getenv("DB_URL", "sqlite+pysqlite:///:memory:")
    pii_hash_salt = os.getenv("PII_HASH_SALT", "development-salt")
    metrics_port_str = os.getenv("METRICS_PORT", str(DEFAULT_METRICS_PORT))
    env = os.getenv("ENV", "dev")

    try:
        metrics_port = int(metrics_port_str)
        if not (1 <= metrics_port <= 65535):
            raise ValueError
    except ValueError as exc:
        raise ValueError("METRICS_PORT must be a valid TCP port") from exc

    if env not in SUPPORTED_ENVS:
        raise ValueError(f"ENV must be one of {sorted(SUPPORTED_ENVS)}")

    typed_env = cast(Literal["dev", "stage", "prod"], env)

    return ServiceConfig(
        db_url=db_url,
        pii_hash_salt=pii_hash_salt,
        metrics_port=metrics_port,
        env=typed_env,
    )
