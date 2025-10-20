from __future__ import annotations

from datetime import date, datetime
import re
import random
from typing import Dict, List, Literal, Optional

from pydantic.dataclasses import dataclass
from dataclasses import field

from sma.core.datetime_utils import utc_now
from sma.shared.counter_rules import COUNTER_PREFIX_MAP


def validate_national_code(code: str) -> bool:
    """اعتبارسنجی کدملی ایران (۱۰ رقمی)."""
    if not code or not code.isdigit() or len(code) != 10:
        return False
    if len(set(code)) == 1:  # همه ارقام یکسان
        return False
    checksum = sum(int(code[i]) * (10 - i) for i in range(9))
    remainder = checksum % 11
    check_digit = int(code[9])
    if remainder < 2:
        return check_digit == remainder
    return check_digit == 11 - remainder


def validate_iranian_phone(phone: str) -> bool:
    """اعتبارسنجی شماره تلفن ایران (همراه/ثابت)."""
    clean_phone = re.sub(r"[\s-]", "", phone or "")
    mobile_pattern = r"^(\+98|0098|98|0)?9[0-9]{9}$"
    landline_pattern = r"^(\+98|0098|98|0)?[2-8][0-9]{7,10}$"
    return bool(re.match(mobile_pattern, clean_phone) or re.match(landline_pattern, clean_phone))


@dataclass
class StudentDTO:
    """مدل دانش‌آموز (ساختار واقعی آموزشگاه).

    ویژگی‌ها:
        student_id: شناسه یکتا.
        counter: شمارنده ۹ رقمی «YY + (357/373) + ####».
        first_name: نام.
        last_name: نام خانوادگی.
        national_code: کدملی ۱۰ رقمی.
        phone: تلفن همراه/ثابت ایران.
        birth_date: تاریخ تولد.
        gender: جنسیت (0=دختر، 1=پسر).
        education_status: وضعیت تحصیل (0=فارغ‌التحصیل، 1=درحال تحصیل).
        registration_status: نوع ثبت‌نام (0=عادی، 1=شهید، 2=حکمت).
        center: مرکز (1=مرکز، 2=گلستان، 3=صدرا).
        grade_level: مقطع/گروه آموزشی.
        school_type: نوع ثبت‌نام مدرسه‌ای (normal/school).
        school_code: کد مدرسه در صورت مدرسه‌ای.
        created_at: زمان ایجاد.
        updated_at: زمان بروزرسانی.
        allocation_status: وضعیت تخصیص.
    """

    student_id: int
    counter: str
    first_name: str
    last_name: str
    national_code: str
    phone: str
    birth_date: date
    gender: Literal[0, 1]
    education_status: Literal[0, 1]
    registration_status: Literal[0, 1, 2]
    center: Literal[1, 2, 3]
    grade_level: str
    school_type: Literal["normal", "school"]
    school_code: Optional[str]
    created_at: datetime
    updated_at: datetime
    allocation_status: Optional[str] = None

    @property
    def id(self) -> int:
        """Provide compatibility alias for student_id."""
        return self.student_id

    @property
    def level(self) -> str:
        """Compatibility alias for grade_level used by legacy callers."""
        return self.grade_level

    @level.setter
    def level(self, value: str) -> None:
        self.grade_level = (value or "unknown")


def migrate_student_dto(old_dto: Dict) -> StudentDTO:
    """مهاجرت ساختار قدیم دانش‌آموز به ساختار جدید StudentDTO."""
    data = dict(old_dto)
    # نام را تفکیک کن
    if "name" in data and ("first_name" not in data or "last_name" not in data):
        parts = str(data.get("name", "")).strip().split(" ", 1)
        data["first_name"] = parts[0] if parts and parts[0] else ""
        data["last_name"] = parts[1] if len(parts) > 1 else ""
    # نگاشت فیلدها
    mapping = {
        "id": "student_id",
        "registration_type": "registration_status",
        "level": "grade_level",
    }
    for old, new in mapping.items():
        if old in data and new not in data:
            data[new] = data.pop(old)

    # school_type تبدیل 0/1 به normal/school
    st = data.get("school_type")
    if isinstance(st, int):
        data["school_type"] = "school" if st == 1 else "normal"
    elif st in ("0", "1"):
        data["school_type"] = "school" if st == "1" else "normal"
    elif st not in ("normal", "school"):
        data["school_type"] = "normal"

    # افزودن فیلدهای ضروری با پیش‌فرض
    if "national_code" not in data:
        data["national_code"] = f"{random.randint(1000000000, 9999999999)}"  # برای داده‌های آزمایشی از random استفاده می‌کنیم؛ حساسیت امنیتی وجود ندارد. # nosec B311
    if "phone" not in data:
        data["phone"] = f"09{random.randint(100000000, 999999999)}"  # برای داده‌های آزمایشی از random استفاده می‌کنیم؛ حساسیت امنیتی وجود ندارد. # nosec B311
    if "birth_date" not in data:
        data["birth_date"] = date(2003, 1, 1)
    if "updated_at" not in data:
        data["updated_at"] = data.get("created_at", utc_now())

    # counter اطمینان از وجود
    if "counter" not in data:
        year = utc_now().year % 100
        gender_value = int(data.get("gender", 1))
        middle = COUNTER_PREFIX_MAP.get(gender_value, COUNTER_PREFIX_MAP[0])
        serial = random.randint(1, 9999)  # تولید سریال برای داده ساختگی است و نیازی به PRNG امن ندارد. # nosec B311
        data["counter"] = f"{year:02d}{middle}{serial:04d}"

    return StudentDTO(**data)


@dataclass
class MentorDTO:
    """مدل منتور.

    ویژگی‌ها:
        id: شناسه یکتا.
        name: نام کامل (فارسی).
        gender: جنسیت (0=دختر، 1=پسر).
        capacity: ظرفیت حداکثری دانش‌آموز.
        current_load: تعداد فعلی دانش‌آموزان تخصیص‌داده‌شده.
        allowed_groups: گروه‌های مجاز مانند «konkoori»، «motavassete2».
        allowed_centers: مراکز مجاز [1, 2, 3].
        is_school_mentor: آیا منتور مدرسه‌ای است.
        school_codes: کدهای مدرسه مجاز.
        is_active: وضعیت فعال بودن.
    """

    id: int
    name: str
    gender: Literal[0, 1]
    capacity: int = 60
    current_load: int = 0
    allowed_groups: List[str] = field(default_factory=list)
    allowed_centers: List[int] = field(default_factory=list)
    is_school_mentor: bool = False
    school_codes: List[str] = field(default_factory=list)
    is_active: bool = True


@dataclass
class AllocationDTO:
    """مدل تخصیص دانش‌آموز به منتور."""

    id: int
    student_id: int
    mentor_id: int
    status: Literal["OK", "TEMP_REVIEW", "NEEDS_NEW_MENTOR"]
    created_at: datetime
    notes: Optional[str] = None


@dataclass
class DashboardStatsDTO:
    """آمار داشبورد مدیریتی تخصیص‌ها و ظرفیت‌ها."""

    total_students: int
    total_mentors: int
    total_allocations: int
    allocation_success_rate: float
    capacity_utilization: float
    status_breakdown: Dict[str, int]


# ---- Optional: نتایج اعتبارسنجی ورود اکسل (برای سازگاری سطح مدل) ----
from dataclasses import dataclass as _dc  # type: ignore[override]


@_dc
class StudentRowValidationResultModel:
    is_valid: bool
    student_data: Dict[str, object] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@_dc
class ImportValidationResultModel:
    success: bool
    total_rows: int = 0
    valid_rows: List[Dict[str, object]] = field(default_factory=list)
    invalid_rows: List[Dict[str, object]] = field(default_factory=list)
    error: Optional[str] = None
