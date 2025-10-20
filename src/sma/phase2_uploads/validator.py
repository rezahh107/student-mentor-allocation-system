from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .errors import UploadError, envelope
from .normalizer import fold_digits, normalize_text_fields

REQUIRED_COLUMNS = (
    "student_id",
    "school_code",
    "mobile",
    "national_id",
    "first_name",
    "last_name",
)
TEXT_FIELDS = ("first_name", "last_name")
PHONE_REGEX = re.compile(r"^09\d{9}$")


@dataclass(slots=True)
class ValidationResult:
    record_count: int
    preview_rows: List[dict[str, str]]


class CSVValidator:
    def __init__(self, *, preview_rows: int = 5) -> None:
        self.preview_rows = preview_rows

    def _ensure_header(self, header: Iterable[str]) -> None:
        missing = [col for col in REQUIRED_COLUMNS if col not in header]
        if missing:
            details = {"missing_columns": missing}
            raise UploadError(envelope("UPLOAD_VALIDATION_ERROR", details=details))

    def validate(self, path: Path) -> ValidationResult:
        try:
            fh = path.open("r", encoding="utf-8", newline="")
        except UnicodeDecodeError:
            raise UploadError(
                envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "UTF8_REQUIRED"})
            ) from None

        try:
            with fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames is None:
                    raise UploadError(
                        envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "HEADER_REQUIRED"})
                    )
                self._ensure_header(reader.fieldnames)
                count = 0
                preview: List[dict[str, str]] = []
                for row in reader:
                    if not any(row.values()):
                        continue
                    try:
                        normalized = normalize_text_fields(TEXT_FIELDS, row)
                    except ValueError as exc:
                        raise UploadError(
                            envelope(
                                "UPLOAD_VALIDATION_ERROR",
                                details={"reason": "FORMULA_GUARD", "row": count + 2},
                            )
                        ) from exc
                    school_code_raw = fold_digits(normalized.get("school_code")) or ""
                    if not school_code_raw:
                        raise UploadError(
                            envelope(
                                "UPLOAD_VALIDATION_ERROR",
                                details={"reason": "SCHOOL_CODE_REQUIRED", "row": count + 2},
                            )
                        )
                    try:
                        school_code = int(school_code_raw)
                    except ValueError:
                        raise UploadError(
                            envelope(
                                "UPLOAD_VALIDATION_ERROR",
                                details={"reason": "SCHOOL_CODE_INVALID", "row": count + 2},
                            )
                        )
                    if school_code <= 0:
                        raise UploadError(
                            envelope(
                                "UPLOAD_VALIDATION_ERROR",
                                details={"reason": "SCHOOL_CODE_POSITIVE", "row": count + 2},
                            )
                        )

                    mobile = fold_digits(normalized.get("mobile")) or ""
                    if mobile and not PHONE_REGEX.fullmatch(mobile):
                        raise UploadError(
                            envelope(
                                "UPLOAD_VALIDATION_ERROR",
                                details={"reason": "MOBILE_INVALID", "row": count + 2},
                            )
                        )

                    normalized["school_code"] = str(school_code)
                    normalized["mobile"] = mobile
                    count += 1
                    if len(preview) < self.preview_rows:
                        preview.append({key: normalized.get(key, "") or "" for key in REQUIRED_COLUMNS})
                return ValidationResult(record_count=count, preview_rows=preview)
        except UnicodeDecodeError as exc:
            raise UploadError(
                envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "UTF8_REQUIRED"})
            ) from exc
