from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from typing import Optional

ZERO_WIDTH = {"\u200c", "\u200d", "\ufeff"}
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PERSIAN_DIGITS = {
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",
    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
}


def fold_digits(value: str) -> str:
    return "".join(PERSIAN_DIGITS.get(ch, ch) for ch in value)


def sanitize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    for zw in ZERO_WIDTH:
        normalized = normalized.replace(zw, "")
    normalized = normalized.replace("\r", " ").replace("\n", " ")
    normalized = CONTROL_RE.sub("", normalized)
    return normalized.strip()


def sanitize_phone(value: Optional[str]) -> str:
    text = sanitize_text(value)
    text = fold_digits(text)
    return text


def guard_formula(value: str) -> str:
    if not value:
        return value
    if value[0] in "=+-@":
        return "'" + value
    return value


def always_quote(value: str) -> str:
    return value


def mask_mobile(mobile: Optional[str]) -> str:
    mobile = sanitize_phone(mobile)
    if len(mobile) < 4:
        return mobile
    return mobile[:4] + "****" + mobile[-2:]


def hash_national_id(national_id: Optional[str]) -> str:
    if not national_id:
        return ""
    normalized = sanitize_text(national_id)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:10]


def deterministic_jitter(base_delay: float, attempt: int, seed: str) -> float:
    rnd = random.Random(hashlib.md5(f"{seed}:{attempt}".encode()).digest())
    return base_delay * (2 ** (attempt - 1)) * (1 + rnd.random() * 0.1)


def dumps_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
