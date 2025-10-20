from __future__ import annotations

SENSITIVE_COLUMNS: tuple[str, ...] = (
    "national_id",
    "counter",
    "mobile",
    "mentor_id",
    "school_code",
)

RISKY_FORMULA_PREFIXES = ("=", "+", "-", "@")

DEFAULT_CHUNK_SIZE = 50_000

SHEET_TEMPLATE = "Sheet_{:03d}"

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {".xlsx", ".csv", ".zip"}
