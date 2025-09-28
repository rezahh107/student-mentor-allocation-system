from __future__ import annotations

import json
import logging
import os
import random
import time
from hashlib import sha256
from typing import Any, Dict

MOBILE_MASK = "09*********"


def mask_mobile(value: str | None) -> str | None:
    if not value:
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 11 and digits.startswith("09"):
        return digits[:4] + "*****" + digits[-2:]
    return value


def hash_national_id(value: str | None) -> str | None:
    if not value:
        return value
    digest = sha256(value.encode("utf-8")).hexdigest()
    return digest[:16]


def setup_json_logging() -> logging.Logger:
    logger = logging.getLogger("uploads")
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:  # noqa: D401
            payload: Dict[str, Any] = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.args and isinstance(record.args, dict):
                payload.update(record.args)
            for key, value in record.__dict__.items():
                if key.startswith("ctx_"):
                    payload[key[4:]] = value
            return json.dumps(payload, ensure_ascii=False)

    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def get_debug_context(extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    context = {
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": time.time(),
        "rand": random.random(),
    }
    if extra:
        context.update(extra)
    return context
