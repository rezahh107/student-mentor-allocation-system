from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from typing import BinaryIO, Iterable, Optional, Union

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


ByteChunk = Union[bytes, bytearray, memoryview]
StreamSource = Union[str, ByteChunk, Iterable[Union[str, ByteChunk]], BinaryIO]


def _normalize_chunk(chunk: Union[str, ByteChunk]) -> bytes:
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    if isinstance(chunk, memoryview):
        return chunk.tobytes()
    if isinstance(chunk, (bytes, bytearray)):
        return bytes(chunk)
    raise TypeError("Unsupported chunk type for secure_digest")


def secure_digest(source: StreamSource) -> str:
    """Compute a SHA-256 hex digest for arbitrary byte/stream inputs."""

    hasher = hashlib.sha256()

    def update_from(chunk: Union[str, ByteChunk]) -> None:
        hasher.update(_normalize_chunk(chunk))

    if isinstance(source, (str, bytes, bytearray, memoryview)):
        update_from(source)
        return hasher.hexdigest()

    if hasattr(source, "read"):
        reader = source  # type: ignore[assignment]
        while True:
            chunk = reader.read(8192)
            if chunk in (b"", ""):
                break
            update_from(chunk)  # type: ignore[arg-type]
        return hasher.hexdigest()

    try:
        iterator = iter(source)  # type: ignore[arg-type]
    except TypeError as exc:  # pragma: no cover - defensive branch
        raise TypeError("Unsupported source type for secure_digest") from exc

    for chunk in iterator:
        update_from(chunk)  # type: ignore[arg-type]
    return hasher.hexdigest()


def fold_digits(value: str) -> str:
    return "".join(PERSIAN_DIGITS.get(ch, ch) for ch in value)


def sanitize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    if value and value.isascii():
        stripped = value.strip()
        if all(" " <= ch <= "~" for ch in stripped):
            return stripped
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("ي", "ی").replace("ك", "ک")
    for zw in ZERO_WIDTH:
        normalized = normalized.replace(zw, "")
    normalized = normalized.replace("\r", " ").replace("\n", " ")
    normalized = CONTROL_RE.sub("", normalized)
    normalized = fold_digits(normalized)
    return normalized.strip()


def sanitize_phone(value: Optional[str]) -> str:
    text = sanitize_text(value)
    text = fold_digits(text)
    return text


def guard_formula(value: str) -> str:
    if not value:
        return value
    risky_prefixes = ("=", "+", "-", "@", "\t", "'", '"')
    first = value[0]
    if first in risky_prefixes:
        if value.startswith("'") and len(value) > 1:
            second = value[1]
            if second in ("=", "+", "-", "@", "\t", '"', "'"):
                return value
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
    digest = secure_digest(normalized)
    return digest[:10]


def deterministic_jitter(base_delay: float, attempt: int, seed: str) -> float:
    digest = secure_digest(f"{seed}:{attempt}")
    rnd_seed = int(digest, 16)
    rnd = random.Random(rnd_seed)
    return base_delay * (2 ** (attempt - 1)) * (1 + rnd.random() * 0.1)


def dumps_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
