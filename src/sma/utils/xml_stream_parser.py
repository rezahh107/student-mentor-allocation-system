"""پارسر جریانی XML برای فایل‌های بزرگ."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, Iterator
import xml.etree.ElementTree as ET  # nosec B405 - در غیاب defusedxml تنها برای ورودی‌های محلی استفاده می‌شود.

SAFE_PARSER: Any

try:
    SAFE_PARSER = importlib.import_module("defusedxml.ElementTree")
except ImportError:
    logging.warning(
        "استفاده از ElementTree استاندارد - برای امنیت بیشتر defusedxml را نصب کنید"
    )
    SAFE_PARSER = ET


LOGGER = logging.getLogger(__name__)


def parse_xml_stream(file_path: str | Path, target_element: str) -> Iterator[Dict[str, Any]]:
    """پردازش جریانی XML بدون بارگذاری کامل در حافظه."""

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"فایل XML یافت نشد: {path}")

    try:
        for event, elem in SAFE_PARSER.iterparse(str(path), events=("start", "end")):
            if event == "end" and elem.tag == target_element:
                payload: Dict[str, Any] = {
                    "tag": elem.tag,
                    "text": elem.text,
                    "attrib": dict(elem.attrib),
                }
                elem.clear()
                yield payload
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("خطا در پردازش جریانی XML %s: %s", path, exc)
        raise


__all__ = ["parse_xml_stream"]
