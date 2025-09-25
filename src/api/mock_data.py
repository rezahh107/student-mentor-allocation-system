from __future__ import annotations

import itertools
import logging
import random
from dataclasses import field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Literal, Optional

from dateutil.relativedelta import relativedelta
from dateutil import parser as dateparser

from .exceptions import BusinessRuleException, ValidationException
from .models import (
    AllocationDTO,
    DashboardStatsDTO,
    MentorDTO,
    StudentDTO,
    validate_national_code,
)


class MockBackend:
    """Backend Mock با داده‌های واقع‌گرایانه برای توسعه UI.

    این کلاس مجموعه‌ای از داده‌های ثابت اما قابل بازتولید تولید می‌کند تا
    نیازمندی‌های توزیع جمعیتی و قواعد تخصیص را پوشش دهد.
    """

    def __init__(self) -> None:
        self._rng = random.Random(42)
        self._students: List[StudentDTO] = []
        self._mentors: List[MentorDTO] = []
        self._allocations: List[AllocationDTO] = []
        self._counters: Dict[int, int] = {0: 0, 1: 0}  # gender -> serial
        self._used_national_codes: set[str] = set()
        self._generate_all()

    # ----------------------- public API -----------------------
    def reset(self) -> None:
        self._rng.seed(42)
        self._students.clear()
        self._mentors.clear()
        self._allocations.clear()
        self._counters = {0: 0, 1: 0}
        self._generate_all()

    async def get_students(self, filters: Optional[Dict] = None) -> List[StudentDTO]:
        data = list(self._students)
        if filters:
            data = [s for s in data if self._apply_student_filters(s, filters)]
        return data

    async def get_students_paginated(self, filters: Optional[Dict] = None) -> Dict:
        """دریافت لیست صفحه‌بندی‌شده دانش‌آموزان.

        ورودی فیلتر می‌تواند شامل page و page_size باشد.
        خروجی: {"students": List[StudentDTO], "total_count": int}
        """
        page = int(filters.get("page", 1)) if filters else 1
        size = int(filters.get("page_size", 20)) if filters else 20
        filt = dict(filters or {})
        filt.pop("page", None)
        filt.pop("page_size", None)

        all_items = await self.get_students(filt)
        total = len(all_items)
        start = (page - 1) * size
        end = start + size
        return {"students": all_items[start:end], "total_count": total}

    async def get_mentors(self, active_only: bool = True) -> List[MentorDTO]:
        if active_only:
            return [m for m in self._mentors if m.is_active]
        return list(self._mentors)

    async def create_allocation(self, student_id: int, mentor_id: int) -> AllocationDTO:
        student = self._by_id(self._students, student_id)
        mentor = self._by_id(self._mentors, mentor_id)
        if not student or not mentor:
            raise BusinessRuleException("دانش‌آموز یا منتور یافت نشد.")

        # قوانین تخصیص
        if mentor.current_load >= mentor.capacity:
            raise BusinessRuleException("ظرفیت منتور تکمیل است.")
        if student.gender != mentor.gender:
            raise BusinessRuleException("عدم انطباق جنسیت دانش‌آموز و منتور.")
        if student.grade_level not in mentor.allowed_groups:
            raise BusinessRuleException("گروه دانش‌آموز در لیست مجاز منتور نیست.")
        if student.center not in mentor.allowed_centers:
            raise BusinessRuleException("مرکز دانش‌آموز توسط منتور پوشش داده نمی‌شود.")
        if student.school_type == "school":
            if not mentor.is_school_mentor:
                raise BusinessRuleException("دانش‌آموز مدرسه‌ای به منتور غیرمدرسه‌ای قابل تخصیص نیست.")
            if student.school_code not in mentor.school_codes:
                raise BusinessRuleException("کد مدرسه دانش‌آموز در لیست منتور نیست.")
        else:
            if mentor.is_school_mentor:
                raise BusinessRuleException("دانش‌آموز عادی به منتور مدرسه‌ای تخصیص نمی‌یابد.")

        alloc_id = (self._allocations[-1].id + 1) if self._allocations else 1
        alloc = AllocationDTO(
            id=alloc_id,
            student_id=student_id,
            mentor_id=mentor_id,
            status="OK",
            created_at=datetime.utcnow(),
            notes=None,
        )
        self._allocations.append(alloc)
        mentor.current_load += 1
        student.allocation_status = "OK"
        return alloc

    # Ranking utility for tests and auto-allocation flows
    def rank_mentors_for_student(self, student: StudentDTO) -> List[MentorDTO]:
        """بازگرداندن منتورهای سازگار به‌ترتیب ظرفیت باقیمانده (نزولی) سپس ID صعودی."""
        compatible = [
            m
            for m in self._mentors
            if (m.gender == student.gender)
            and (student.grade_level in m.allowed_groups)
            and (student.center in m.allowed_centers)
            and (
                (student.school_type == "school" and m.is_school_mentor and student.school_code in m.school_codes)
                or (student.school_type == "normal" and not m.is_school_mentor)
            )
            and (m.current_load < m.capacity)
        ]
        compatible.sort(key=lambda m: (-(m.capacity - m.current_load), m.id))
        return compatible

    async def get_dashboard_stats(self) -> DashboardStatsDTO:
        ok = sum(1 for a in self._allocations if a.status == "OK")
        tr = sum(1 for a in self._allocations if a.status == "TEMP_REVIEW")
        nn = sum(1 for a in self._allocations if a.status == "NEEDS_NEW_MENTOR")
        total_allocs = len(self._allocations)

        total_capacity = sum(m.capacity for m in self._mentors if m.is_active)
        total_load = sum(m.current_load for m in self._mentors if m.is_active)
        util = (total_load / total_capacity) * 100 if total_capacity else 0.0
        success_rate = (ok / total_allocs) * 100 if total_allocs else 0.0

        return DashboardStatsDTO(
            total_students=len(self._students),
            total_mentors=len(self._mentors),
            total_allocations=total_allocs,
            allocation_success_rate=round(success_rate, 2),
            capacity_utilization=round(util, 2),
            status_breakdown={
                "OK": ok,
                "TEMP_REVIEW": tr,
                "NEEDS_NEW_MENTOR": nn,
            },
        )

    async def get_next_counter(self, gender: int) -> str:
        return self._next_counter(int(gender))

    async def health_check(self) -> bool:
        return True

    async def create_student(self, data: Dict) -> StudentDTO:
        """ایجاد دانش‌آموز جدید در Mock Backend (ساختار جدید)."""
        new_id = (self._students[-1].student_id + 1) if self._students else 1
        gender = int(data.get("gender", 1))
        first = data.get("first_name") or (str(data.get("name", "")).split(" ", 1)[0] if data.get("name") else "دانش‌آموز")
        last = data.get("last_name") or (str(data.get("name", "")).split(" ", 1)[1] if data.get("name") and len(str(data.get("name")).split(" ", 1)) > 1 else "")

        # phone & national_code
        national_code = str(data.get("national_code") or self._generate_national_code())
        phone = str(data.get("phone") or self._generate_phone())

        # birth_date
        bd = data.get("birth_date")
        if isinstance(bd, str):
            try:
                bd = datetime.fromisoformat(bd).date()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("تبدیل تاریخ تولد ورودی ناموفق بود", exc_info=exc)
                bd = self._generate_birth_date()
        if not isinstance(bd, date):
            bd = self._generate_birth_date()

        # school_type normalization
        st = data.get("school_type", "normal")
        if isinstance(st, int):
            st = "school" if st == 1 else "normal"
        elif st not in ("normal", "school"):
            st = "normal"
        sc_code = data.get("school_code")
        if st == "school" and not sc_code:
            sc_code = self._rng.choice(["SCH-1001", "SCH-1002", "SCH-2001"])

        # validate grade level
        allowed_levels = ["konkoori", "motavassete2", "motavassete1"]
        gl = str(data.get("grade_level", data.get("level", "konkoori")))
        if gl not in allowed_levels:
            raise ValidationException("مقطع/گروه آموزشی نامعتبر است.")

        student = StudentDTO(
            student_id=new_id,
            counter=self._next_counter(gender),
            first_name=str(first),
            last_name=str(last),
            national_code=national_code,
            phone=phone,
            birth_date=bd,
            gender=gender,  # type: ignore[arg-type]
            education_status=int(data.get("education_status", 1)),  # type: ignore[arg-type]
            registration_status=int(data.get("registration_status", data.get("registration_type", 0))),  # type: ignore[arg-type]
            center=int(data.get("center", 1)),  # type: ignore[arg-type]
            grade_level=gl,
            school_type=st,  # type: ignore[arg-type]
            school_code=sc_code,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            allocation_status=None,
        )
        if student.school_type == "school" and not student.school_code:
            raise BusinessRuleException("برای دانش‌آموز مدرسه‌ای، کد مدرسه الزامی است.")
        self._students.append(student)
        return student

    async def update_student(self, student_id: int, data: Dict) -> StudentDTO:
        s = self._by_id(self._students, student_id)
        if not s:
            raise BusinessRuleException("دانش‌آموز یافت نشد")
        if "first_name" in data:
            s.first_name = str(data["first_name"])  # type: ignore[assignment]
        if "last_name" in data:
            s.last_name = str(data["last_name"])  # type: ignore[assignment]
        if "name" in data and ("first_name" not in data and "last_name" not in data):
            parts = str(data["name"]).split(" ", 1)
            s.first_name = parts[0]
            s.last_name = parts[1] if len(parts) > 1 else ""
        if "gender" in data:
            s.gender = int(data["gender"])  # type: ignore[assignment]
        if "education_status" in data:
            s.education_status = int(data["education_status"])  # type: ignore[assignment]
        if "registration_status" in data:
            s.registration_status = int(data["registration_status"])  # type: ignore[assignment]
        if "registration_type" in data and "registration_status" not in data:
            s.registration_status = int(data["registration_type"])  # type: ignore[assignment]
        if "center" in data:
            s.center = int(data["center"])  # type: ignore[assignment]
        if "grade_level" in data or "level" in data:
            gl = str(data.get("grade_level", data.get("level", s.grade_level)))
            if gl not in ["konkoori", "motavassete2", "motavassete1"]:
                raise ValidationException("مقطع/گروه آموزشی نامعتبر است.")
            s.grade_level = gl
        if "school_type" in data:
            st = data["school_type"]
            if isinstance(st, int):
                st = "school" if st == 1 else "normal"
            s.school_type = st  # type: ignore[assignment]
        if "school_code" in data:
            s.school_code = data["school_code"]
        if "national_code" in data and validate_national_code(str(data["national_code"])):
            s.national_code = str(data["national_code"])  # type: ignore[assignment]
        if "phone" in data:
            s.phone = str(data["phone"])  # type: ignore[assignment]
        if "birth_date" in data:
            bd = data["birth_date"]
            if isinstance(bd, str):
                try:
                    bd = datetime.fromisoformat(bd).date()
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).warning("تبدیل تاریخ تولد به‌روزرسانی‌شونده ممکن نشد", exc_info=exc)
                    bd = s.birth_date
            s.birth_date = bd  # type: ignore[assignment]
        s.updated_at = datetime.utcnow()
        return s

    async def delete_student(self, student_id: int) -> bool:
        s = self._by_id(self._students, student_id)
        if not s:
            raise BusinessRuleException("دانش‌آموز یافت نشد")
        # حذف تخصیص‌های مرتبط
        self._allocations = [a for a in self._allocations if a.student_id != student_id]
        self._students = [st for st in self._students if st.id != student_id]
        return True

    # ----------------------- internals -----------------------
    def _apply_student_filters(self, s: StudentDTO, f: Dict) -> bool:
        for k, v in f.items():
            if v is None:
                continue
            if k == "gender" and s.gender != v:
                return False
            if k == "center" and s.center != v:
                return False
            if k == "education_status" and s.education_status != v:
                return False
            if k == "registration_status" and s.registration_status != v:
                return False
            if k == "school_type" and s.school_type != v:
                return False
            if k == "grade_level" and s.grade_level != v:
                return False
            if k == "allocation_status" and s.allocation_status != v:
                return False
            if k == "created_at__gte" and v:
                try:
                    dt = dateparser.parse(str(v))
                    if not (s.created_at >= dt):
                        return False
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).warning("تحلیل created_at__gte ناموفق بود", exc_info=exc)
            if k == "created_at__lte" and v:
                try:
                    dt = dateparser.parse(str(v))
                    if not (s.created_at <= dt):
                        return False
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).warning("تحلیل created_at__lte ناموفق بود", exc_info=exc)
            if k == "first_name_search" and v:
                if str(v).strip() not in s.first_name:
                    return False
            if k == "last_name_search" and v:
                if str(v).strip() not in s.last_name:
                    return False
            if k == "name_search" and v:
                # سازگاری عقب‌رو: جستجو در هر دو فیلد
                val = str(v).strip()
                if val not in s.first_name and val not in s.last_name:
                    return False
            if k == "counter_search" and v:
                if not str(s.counter).startswith(str(v)):
                    return False
            if k == "national_code" and v:
                if not str(s.national_code).startswith(str(v)):
                    return False
            if k == "phone" and v:
                if str(v) not in s.phone and str(v) not in self._normalize_phone(s.phone):
                    return False
        return True

    def _generate_all(self) -> None:
        # دانش‌آموزان
        self._students = self._gen_students(n=50)
        # منتورها
        self._mentors = self._gen_mentors(n=15)
        # تخصیص‌ها
        self._allocations = self._gen_allocations(target=35)

        # ثبت وضعیت تخصیص در دانش‌آموزان تخصیص داده‌شده
        alloc_by_student = {a.student_id: a for a in self._allocations}
        for s in self._students:
            if s.student_id in alloc_by_student:
                s.allocation_status = alloc_by_student[s.student_id].status

    def _gen_students(self, n: int) -> List[StudentDTO]:
        # توزیع‌ها
        females = int(round(n * 0.30))
        males = n - females
        studying = int(round(n * 0.80))
        graduated = n - studying
        center1 = int(round(n * 0.50))
        center2 = int(round(n * 0.30))
        center3 = n - center1 - center2
        school_based = int(round(n * 0.15))

        PERSIAN_FIRST_NAMES = {
            "male": ["علی", "محمد", "حسین", "رضا", "احمد", "مهدی", "حسن", "امیر"],
            "female": ["فاطمه", "زهرا", "مریم", "آیدا", "سارا", "نازنین", "الهام", "مهسا"],
        }
        PERSIAN_LAST_NAMES = [
            "احمدی",
            "محمدی",
            "حسینی",
            "رضایی",
            "موسوی",
            "کریمی",
            "حسنی",
            "صادقی",
            "مرادی",
            "فتحی",
            "نوری",
            "جعفری",
        ]
        levels = ["konkoori", "motavassete2", "motavassete1"]
        school_codes = ["SCH-1001", "SCH-1002", "SCH-1003", "SCH-2001", "SCH-3001"]

        now = datetime.utcnow()
        students: List[StudentDTO] = []

        genders = [0] * females + [1] * males
        self._rng.shuffle(genders)
        edu_statuses = [1] * studying + [0] * graduated
        self._rng.shuffle(edu_statuses)
        centers = [1] * center1 + [2] * center2 + [3] * center3
        self._rng.shuffle(centers)
        # مدرسه‌ای
        school_flags = [1] * school_based + [0] * (n - school_based)
        self._rng.shuffle(school_flags)

        for i in range(1, n + 1):
            g = genders[i - 1]
            first = self._rng.choice(
                PERSIAN_FIRST_NAMES["female" if g == 0 else "male"]
            )
            last = self._rng.choice(PERSIAN_LAST_NAMES)
            edu = edu_statuses[i - 1]
            c = centers[i - 1]
            is_school = school_flags[i - 1] == 1
            sc_code = self._rng.choice(school_codes) if is_school else None
            level = self._rng.choice(levels)
            reg_status = self._rng.choices([0, 1, 2], weights=[70, 10, 20], k=1)[0]

            created_at = now - relativedelta(days=self._rng.randint(0, 180))
            updated_at = created_at + relativedelta(days=self._rng.randint(0, 30))

            students.append(
                StudentDTO(
                    student_id=i,
                    counter=self._next_counter(g),
                    first_name=first,
                    last_name=last,
                    national_code=self._generate_national_code(),
                    phone=self._generate_phone(),
                    birth_date=self._generate_birth_date(),
                    gender=g,  # type: ignore[arg-type]
                    education_status=edu,  # type: ignore[arg-type]
                    registration_status=reg_status,  # type: ignore[arg-type]
                    center=c,  # type: ignore[arg-type]
                    grade_level=level,
                    school_type="school" if is_school else "normal",  # type: ignore[arg-type]
                    school_code=sc_code,
                    created_at=created_at,
                    updated_at=updated_at,
                    allocation_status=None,
                )
            )

        return students

    def _gen_mentors(self, n: int) -> List[MentorDTO]:
        names = [
            "استاد رضوی",
            "استاد محمدی",
            "استاد حسینی",
            "استاد شریفی",
            "استاد احمدی",
            "استاد امینی",
            "استاد مرادی",
            "استاد فاطمی",
            "استاد سمیعی",
            "استاد طاهری",
            "استاد یوسفی",
            "استاد حبیبی",
            "استاد کریمی",
            "استاد رستمی",
            "استاد کاظمی",
        ]
        levels = ["konkoori", "motavassete2", "motavassete1"]

        # 3 منتور مدرسه‌ای
        school_codes = ["SCH-1001", "SCH-1002", "SCH-2001"]

        mentors: List[MentorDTO] = []
        for i in range(1, n + 1):
            is_school = i <= 3
            capacity = self._rng.choice([60, 60, 60, 50, 70, 80, 40])
            gender = self._rng.choice([0, 1])
            allowed_centers = [1, 2, 3]
            allowed_groups = levels.copy()
            codes = [school_codes[(i - 1) % len(school_codes)]] if is_school else []
            mentors.append(
                MentorDTO(
                    id=i,
                    name=names[(i - 1) % len(names)],
                    gender=gender,  # type: ignore[arg-type]
                    capacity=capacity,
                    current_load=0,
                    allowed_groups=allowed_groups,
                    allowed_centers=allowed_centers,
                    is_school_mentor=is_school,
                    school_codes=codes,
                    is_active=True,
                )
            )

        # بار اولیه بین 30% تا 90% ظرفیت، بعداً با تخصیص‌ها آپدیت می‌شود
        for m in mentors:
            m.current_load = int(m.capacity * self._rng.uniform(0.3, 0.9))
        return mentors

    def _gen_allocations(self, target: int) -> List[AllocationDTO]:
        # توزیع وضعیت‌ها: 85% OK، 10% TEMP_REVIEW، 5% NEEDS_NEW_MENTOR
        ok_n = int(round(target * 0.85))
        tr_n = int(round(target * 0.10))
        nn_n = target - ok_n - tr_n

        allocations: List[AllocationDTO] = []
        aid = 1
        now = datetime.utcnow()

        # انتخاب دانش‌آموزان مناسب نسبت به منتورها
        students_pool = list(self._students)
        self._rng.shuffle(students_pool)

        def pick_valid_pairs(sts: Iterable[StudentDTO]) -> List[tuple[StudentDTO, MentorDTO]]:
            pairs: List[tuple[StudentDTO, MentorDTO]] = []
            for s in sts:
                # منتورهای سازگار
                compatible = [
                    m
                    for m in self._mentors
                    if (m.gender == s.gender)
                    and (s.grade_level in m.allowed_groups)
                    and (s.center in m.allowed_centers)
                    and ((s.school_type == "school" and m.is_school_mentor and s.school_code in m.school_codes)
                         or (s.school_type == "normal" and not m.is_school_mentor))
                    and (m.current_load < m.capacity)
                ]
                if compatible:
                    pairs.append((s, self._rng.choice(compatible)))
            return pairs

        pairs = pick_valid_pairs(students_pool)
        used_students: set[int] = set()

        def add_alloc(s: StudentDTO, m: MentorDTO, status: str) -> None:
            nonlocal aid
            allocations.append(
                AllocationDTO(
                    id=aid,
                    student_id=s.student_id,
                    mentor_id=m.id,
                    status=status,  # type: ignore[arg-type]
                    created_at=now - timedelta(days=self._rng.randint(1, 120)),
                    notes=None,
                )
            )
            aid += 1
            m.current_load += 1
            used_students.add(s.student_id)

        # ابتدا OK
        for s, m in pairs:
            if len([a for a in allocations if a.status == "OK"]) >= ok_n:
                break
            add_alloc(s, m, "OK")

        # سپس TEMP_REVIEW
        for s, m in pairs:
            if s.id in used_students:
                continue
            if len([a for a in allocations if a.status == "TEMP_REVIEW"]) >= tr_n:
                break
            add_alloc(s, m, "TEMP_REVIEW")

        # سپس NEEDS_NEW_MENTOR (می‌تواند منتور placeholder باشد)
        for s in students_pool:
            if s.id in used_students:
                continue
            if len([a for a in allocations if a.status == "NEEDS_NEW_MENTOR"]) >= nn_n:
                break
            # اگر منتور سازگار نبود، یک منتور تصادفی هم‌جنس انتخاب می‌کنیم تا حالت نیاز به منتور جدید را مدل کند
            same_gender_mentors = [m for m in self._mentors if m.gender == s.gender]
            m = self._rng.choice(same_gender_mentors) if same_gender_mentors else self._rng.choice(self._mentors)
            add_alloc(s, m, "NEEDS_NEW_MENTOR")

        return allocations[:target]

    def _next_counter(self, gender: int) -> str:
        year = datetime.utcnow().year % 100
        middle = 357 if gender == 0 else 373
        self._counters[gender] += 1
        serial = f"{self._counters[gender]:04d}"
        return f"{year:02d}{middle}{serial}"

    @staticmethod
    def _by_id(items: Iterable, item_id: int):
        for it in items:
            if getattr(it, "id", None) == item_id or getattr(it, "student_id", None) == item_id:
                return it
        return None

    def _generate_national_code(self) -> str:
        # تولید کدملی معتبر و یکتا در محدوده تولید
        while True:
            base = "".join(str(self._rng.randint(0, 9)) for _ in range(9))
            if len(set(base)) == 1:
                continue
            checksum = sum(int(base[i]) * (10 - i) for i in range(9))
            r = checksum % 11
            check = r if r < 2 else 11 - r
            code = f"{base}{check}"
            if code not in self._used_national_codes and validate_national_code(code):
                self._used_national_codes.add(code)
                return code

    def _generate_phone(self) -> str:
        # تولید شماره موبایل ایران با پیش‌شماره +98
        prefix = self._rng.choice(["+98912", "+98913", "+98914", "+98915", "+98919", "+98930", "+98935", "+98936", "+98937", "+98938", "+98939", "+98901", "+98902"])
        rest = "".join(str(self._rng.randint(0, 9)) for _ in range(7))
        return prefix + rest

    def _generate_birth_date(self) -> date:
        # سن ۱۶ تا ۲۵ سال
        years_back = self._rng.randint(16, 25)
        days_offset = self._rng.randint(0, 364)
        dt = datetime.utcnow() - relativedelta(years=years_back, days=days_offset)
        return dt.date()

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        # تبدیل +98xxxxxxxxxx به 0xxxxxxxxxx
        if phone.startswith("+98"):
            rest = phone[3:]
            if rest and rest[0] == "9":
                return "0" + rest
        return phone


# نمونه Singleton برای استفاده آسان توسط کلاینت Mock
mock_backend = MockBackend()
