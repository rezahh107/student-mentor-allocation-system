# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict

from src.infrastructure.monitoring.logging import correlation_id_var


def mask(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def audit_event(event_type: str, payload: Dict[str, Any]) -> str:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "correlation_id": correlation_id_var.get(),
        "payload": payload,
    }
    return json.dumps(record, ensure_ascii=False)

