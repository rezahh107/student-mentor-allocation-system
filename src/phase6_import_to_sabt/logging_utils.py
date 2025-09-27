from __future__ import annotations

import json
import logging
from typing import Any

from .sanitization import dumps_json, hash_national_id, mask_mobile


class ExportLogger:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("phase6.exporter")
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)

    def info(self, message: str, **kwargs: Any) -> None:
        payload = self._prepare_payload("INFO", message, kwargs)
        self._logger.info(payload)

    def error(self, message: str, **kwargs: Any) -> None:
        payload = self._prepare_payload("ERROR", message, kwargs)
        self._logger.error(payload)

    def _prepare_payload(self, level: str, message: str, kwargs: dict[str, Any]) -> str:
        sanitized = {}
        for key, value in kwargs.items():
            if key == "national_id":
                sanitized[key] = hash_national_id(value)
            elif key == "mobile":
                sanitized[key] = mask_mobile(value)
            else:
                sanitized[key] = value
        data = {"level": level, "message": message, **sanitized}
        return dumps_json(data)


def get_export_logger() -> ExportLogger:
    return ExportLogger()
