# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from sma.core.clock import Clock, ensure_clock
from sma.infrastructure.monitoring.logging_adapter import correlation_id_var


def mask(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def audit_event(event_type: str, payload: Dict[str, Any], *, clock: Clock | None = None) -> str:
    """Build a deterministic audit payload with Tehran-aware timestamps."""

    active_clock = ensure_clock(clock, default=Clock.for_tehran())
    record = {
        "ts": active_clock.now().isoformat(),
        "event": event_type,
        "correlation_id": correlation_id_var.get(),
        "payload": payload,
    }
    return json.dumps(record, ensure_ascii=False)

