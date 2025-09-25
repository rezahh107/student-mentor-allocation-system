#!/usr/bin/env python3
"""بررسی نصب وابستگی‌های امنیتی"""
from __future__ import annotations

import logging
import subprocess  # nosec B404 - اجرای pip با پارامترهای ثابت و بدون ورودی کاربر.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.logging_config import setup_logging


def check_security_dependencies() -> bool:
    """بررسی و نصب خودکار وابستگی‌های امنیتی."""

    required_packages = {
        "defusedxml": ">=0.7.1",
        "bandit": ">=1.7.5",
    }

    missing: list[str] = []
    for package, spec in required_packages.items():
        try:
            __import__(package)
            logging.info("✅ %s نصب شده است", package)
        except ImportError:
            requirement = f"{package}{spec}"
            missing.append(requirement)
            logging.warning("❌ %s یافت نشد", package)

    if missing:
        logging.info("در حال نصب وابستگی‌های ناموجود...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])  # nosec B603 - آرگومان‌ها ثابت و بدون داده‌ی کاربر هستند.
        logging.info("✅ همه وابستگی‌ها نصب شدند")
        for package in required_packages:
            __import__(package)
        return True

    logging.info("همه وابستگی‌های امنیتی حاضر هستند")
    return True


if __name__ == "__main__":
    setup_logging()
    try:
        all_present = check_security_dependencies()
    except subprocess.CalledProcessError as error:
        logging.error("نصب وابستگی‌های امنیتی با خطا مواجه شد: %s", error)
        sys.exit(error.returncode or 1)
    if not all_present:
        sys.exit(1)
