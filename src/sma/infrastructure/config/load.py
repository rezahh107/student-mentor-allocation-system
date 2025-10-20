# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

import yaml  # type: ignore


def load_config() -> dict:
    env = os.getenv("APP_ENV", "development")
    p = Path(__file__).parents[3] / "deployment" / "configs" / f"{env}.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8"))

