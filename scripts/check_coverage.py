"""ابزارهای کمکی برای بررسی گزارش پوشش و پارس امن XML."""
from __future__ import annotations

import importlib
import logging
import sys
from typing import Any, Dict, Optional
import xml.etree.ElementTree as ET  # nosec B405 - استفاده صرفاً برای حالت fallback کنترل‌شده است.

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.logging_config import setup_logging

setup_logging()

LOGGER = logging.getLogger(__name__)


def _load_parser():
    """بازیابی ماژول پارسر امن و وضعیت دسترس‌پذیری defusedxml."""

    try:
        defused_tree = importlib.import_module("defusedxml.ElementTree")
        defused_common = importlib.import_module("defusedxml.common")
    except ImportError:
        LOGGER.warning("defusedxml در دسترس نیست؛ از ElementTree استاندارد استفاده می‌کنیم")
        return ET, (ET.ParseError,), False

    defused_exception = getattr(defused_common, "DefusedXmlException", Exception)
    return defused_tree, (defused_exception,), True


def _contains_danger(xml_text: str) -> bool:
    upper_text = xml_text.upper()
    return "<!DOCTYPE" in upper_text or "<!ENTITY" in upper_text


def parse_xml_safely(xml_text: str) -> Optional[Dict[str, Any]]:
    """پارس ایمن XML و بازگرداندن ساختار ساده‌شده."""

    normalized = xml_text.strip()
    if not normalized:
        LOGGER.warning("رشته XML خالی است")
        return None

    parser_module, exception_types, using_defused = _load_parser()

    if not using_defused and _contains_danger(normalized):
        LOGGER.error("XML حاوی ساختار خطرناک است و بدون defusedxml رد شد")
        return None

    try:
        element = parser_module.fromstring(normalized)
    except exception_types as error:  # type: ignore[arg-type]
        LOGGER.error("XML مخرب توسط defusedxml مسدود شد: %s", error)
        return None
    except ET.ParseError as error:
        LOGGER.error("XML نامعتبر است: %s", error)
        return None

    simplified = {
        "tag": element.tag,
        "text": element.text,
        "attrib": dict(element.attrib),
        "children": [child.tag for child in list(element)],
    }
    return simplified


__all__ = ["parse_xml_safely"]
