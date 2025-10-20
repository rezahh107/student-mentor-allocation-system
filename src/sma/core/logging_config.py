"""پیکربندی مرکزی لاگینگ برای کل پروژه."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FILE_DEFAULT = Path("logs/security.log")


def _ensure_directory(log_file: Path) -> None:
    """ایجاد پوشه‌ی والد در صورت نیاز."""

    log_dir = log_file.expanduser().resolve().parent
    log_dir.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO, log_file: str | Path | None = None) -> None:
    """راه‌اندازی لاگینگ با فرمت و هندلر یکسان."""

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    destination: Path | None = None
    if log_file:
        destination = Path(log_file)
    elif log_file is None and _LOG_FILE_DEFAULT:
        destination = _LOG_FILE_DEFAULT

    if destination is not None:
        try:
            _ensure_directory(destination)
        except OSError as error:
            logging.getLogger(__name__).warning(
                "امکان ایجاد پوشه‌ی لاگ وجود ندارد: %s", error
            )
        else:
            file_handler = logging.handlers.RotatingFileHandler(
                destination,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

    logging.info("سیستم لاگینگ راه‌اندازی شد")


__all__ = ["setup_logging"]
