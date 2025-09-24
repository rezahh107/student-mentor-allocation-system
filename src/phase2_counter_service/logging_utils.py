# -*- coding: utf-8 -*-
"""Structured logging helpers for the counter service."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Mapping

from .types import HashFunc, LoggerLike


class StructuredLogger(LoggerLike):
    """Minimal JSON logger wrapper used by the service for deterministic logs."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @staticmethod
    def _render(msg: str, extra: Mapping[str, Any] | None) -> str:
        payload: Dict[str, Any] = {"پیام": msg}
        if extra:
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)

    def info(self, msg: str, *args: Any, extra: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.info(self._render(msg, extra), *args, **kwargs)

    def warning(self, msg: str, *args: Any, extra: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.warning(self._render(msg, extra), *args, **kwargs)

    def error(self, msg: str, *args: Any, extra: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.error(self._render(msg, extra), *args, **kwargs)


def build_logger(name: str = "counter-service") -> StructuredLogger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    return StructuredLogger(logger)


def make_hash_fn(salt: str) -> HashFunc:
    def _hash(national_id: str) -> str:
        digest = hashlib.sha256()
        digest.update(salt.encode("utf-8"))
        digest.update(national_id.encode("utf-8"))
        return digest.hexdigest()

    return _hash
