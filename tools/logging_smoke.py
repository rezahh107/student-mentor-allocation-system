"""Minimal logging smoke test ensuring reserved keys aren't used."""

from __future__ import annotations

import logging

from src.infrastructure.monitoring.logging_adapter import configure_json_logging


def main() -> int:
    configure_json_logging()
    logger = logging.getLogger("tools.logging_smoke")
    logger.info("logging_smoke_start", extra={"detail": "json logging configured"})
    try:
        raise RuntimeError("synthetic smoke exception")
    except RuntimeError as exc:
        logger.exception("logging_smoke_exception", extra={"detail": str(exc)})
    logger.info("logging_smoke_complete", extra={"detail": "ok"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
