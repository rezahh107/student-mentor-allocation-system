# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Dict


class ReasonCode(StrEnum):
    OK = "OK"
    GENDER_MISMATCH = "GENDER_MISMATCH"
    GROUP_NOT_ALLOWED = "GROUP_NOT_ALLOWED"
    CENTER_NOT_ALLOWED = "CENTER_NOT_ALLOWED"
    CAPACITY_FULL = "CAPACITY_FULL"
    GRADUATE_SCHOOL_FORBIDDEN = "GRADUATE_SCHOOL_FORBIDDEN"
    SCHOOL_STUDENT_NEEDS_SCHOOL_MENTOR = "SCHOOL_STUDENT_NEEDS_SCHOOL_MENTOR"
    SCHOOL_CODE_MISMATCH = "SCHOOL_CODE_MISMATCH"
    NORMAL_STUDENT_CANNOT_GET_SCHOOL_MENTOR = "NORMAL_STUDENT_CANNOT_GET_SCHOOL_MENTOR"
    NO_ELIGIBLE_MENTOR = "NO_ELIGIBLE_MENTOR"


_MESSAGES_FA: Dict[ReasonCode, str] = {
    ReasonCode.OK: "قانون با موفقیت گذرانده شد.",
    ReasonCode.GENDER_MISMATCH: "جنسیت دانش‌آموز و مربی هم‌خوان نیست.",
    ReasonCode.GROUP_NOT_ALLOWED: "گروه در فهرست گروه‌های مجاز مربی نیست.",
    ReasonCode.CENTER_NOT_ALLOWED: "مرکز ثبت‌نام دانش‌آموز با مراکز مجاز مربی هماهنگ نیست.",
    ReasonCode.CAPACITY_FULL: "ظرفیت مربی تکمیل شده است.",
    ReasonCode.GRADUATE_SCHOOL_FORBIDDEN: "فارغ‌التحصیل نمی‌تواند به مربی مدرسه تخصیص یابد.",
    ReasonCode.SCHOOL_STUDENT_NEEDS_SCHOOL_MENTOR: "دانش‌آموز مدرسه باید مربی مدرسه داشته باشد.",
    ReasonCode.SCHOOL_CODE_MISMATCH: "کد مدرسه دانش‌آموز با مدرسه‌های مربی منطبق نیست.",
    ReasonCode.NORMAL_STUDENT_CANNOT_GET_SCHOOL_MENTOR: "دانش‌آموز عادی نمی‌تواند مربی مدرسه داشته باشد.",
    ReasonCode.NO_ELIGIBLE_MENTOR: "مربی مناسبی برای این دانش‌آموز یافت نشد.",
}


@dataclass(frozen=True, slots=True)
class LocalizedReason:
    code: ReasonCode
    message_fa: str


@dataclass(frozen=True, slots=True)
class RuleResult:
    ok: bool
    reason: LocalizedReason | None = None

    @property
    def code(self) -> ReasonCode | None:
        return self.reason.code if self.reason else None

    @property
    def message_fa(self) -> str | None:
        return self.reason.message_fa if self.reason else None


def build_reason(code: ReasonCode) -> LocalizedReason:
    return LocalizedReason(code=code, message_fa=_MESSAGES_FA[code])


__all__ = [
    "ReasonCode",
    "LocalizedReason",
    "RuleResult",
    "build_reason",
]

