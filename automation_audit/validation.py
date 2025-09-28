from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import fold_digits

REG_CENTER_ALLOWED = {0, 1, 2}
REG_STATUS_ALLOWED = {0, 1, 3}
PHONE_RE = re.compile(r"^09\d{9}$")


@dataclass
class Enrollment:
    reg_center: int
    reg_status: int
    phone: str

    def validate(self) -> None:
        if self.reg_center not in REG_CENTER_ALLOWED:
            raise ValueError("کد مرکز ثبت‌نام نامعتبر است.")
        if self.reg_status not in REG_STATUS_ALLOWED:
            raise ValueError("وضعیت ثبت‌نام نامعتبر است.")
        normalized_phone = fold_digits(self.phone)
        if not PHONE_RE.fullmatch(normalized_phone):
            raise ValueError("شماره همراه نامعتبر است.")
