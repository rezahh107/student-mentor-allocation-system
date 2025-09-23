# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Iterable


def validate_data_retention(policies: dict) -> bool:
    # Placeholder: ensure retention days within allowed range
    return 30 <= int(policies.get("retention_days", 90)) <= 3650


def enforce_pii_masking(fields: Iterable[str]) -> bool:
    # Ensure required PII fields are masked in logs
    required = {"national_id", "mobile"}
    return required.issubset(set(fields))

