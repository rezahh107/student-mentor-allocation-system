# -*- coding: utf-8 -*-
"""Custom error hierarchy with Persian messages and machine-readable codes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .types import ErrorDetail


@dataclass(frozen=True, slots=True)
class CounterServiceError(Exception):
    """Base class for domain errors exposed to callers."""

    detail: ErrorDetail
    cause: Optional[Exception] = None

    def __str__(self) -> str:  # pragma: no cover - human readable path
        return f"{self.detail.code}: {self.detail.message_fa} ({self.detail.details})"


def invalid_national_id(message: str) -> CounterServiceError:
    return CounterServiceError(
        ErrorDetail("E_INVALID_NID", "کد ملی نامعتبر است.", message),
    )


def invalid_gender(message: str) -> CounterServiceError:
    return CounterServiceError(
        ErrorDetail("E_INVALID_GENDER", "جنسیت نامعتبر است.", message),
    )


def invalid_year_code(message: str) -> CounterServiceError:
    return CounterServiceError(
        ErrorDetail("E_YEAR_CODE_INVALID", "کد سال نامعتبر است.", message),
    )


def db_conflict(message: str, *, cause: Optional[Exception] = None) -> CounterServiceError:
    return CounterServiceError(
        ErrorDetail("E_DB_CONFLICT", "تعارض در پایگاه داده رخ داد.", message),
        cause,
    )


def counter_exhausted(message: str) -> CounterServiceError:
    return CounterServiceError(
        ErrorDetail("E_COUNTER_EXHAUSTED", "ظرفیت شمارنده به پایان رسید.", message),
    )
