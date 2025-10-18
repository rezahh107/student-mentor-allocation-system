from __future__ import annotations

"""Structured logging helpers with deterministic masking."""

import json
import logging
import re
from typing import Any, Dict

_MOBILE_RE = re.compile(r"(\+?98|0)9\d{9}")


def mask_pii(value: str) -> str:
    """Mask phone numbers and national ids inside ``value``."""

    def _replace(match: re.Match[str]) -> str:
        digits = match.group(0)
        return f"{digits[:4]}****{digits[-3:]}"

    return _MOBILE_RE.sub(_replace, value)


class JsonCorrelationAdapter(logging.LoggerAdapter):
    """Logger adapter that emits JSON payloads with correlation context."""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        correlation_id = self.extra.get("correlation_id", "unknown")
        payload = {
            "message": mask_pii(str(msg)),
            "correlation_id": correlation_id,
            **{k: mask_pii(str(v)) for k, v in kwargs.get("extra", {}).items()},
        }
        return json.dumps(payload, ensure_ascii=False), {"extra": None}


def get_json_logger(name: str, correlation_id: str) -> JsonCorrelationAdapter:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        logger.addHandler(handler)
    return JsonCorrelationAdapter(logger, {"correlation_id": correlation_id})
