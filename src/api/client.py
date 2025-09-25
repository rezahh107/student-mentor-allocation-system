from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

from .config import APIConfig
from .exceptions import (
    APIException,
    BusinessRuleException,
    NetworkException,
    ValidationException,
)
from .mock_data import mock_backend
from .models import AllocationDTO, DashboardStatsDTO, MentorDTO, StudentDTO, migrate_student_dto


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("api.client")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt=(
                "%(asctime)s | level=%(levelname)s | module=%(name)s | "
                "message=%(message)s"
            )
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class APIClient:
    """کلاینت یکپارچه API با پشتیبانی Mock/Real.

    قابلیت‌ها:
        - تلاش مجدد خودکار با Backoff نمایی
        - لاگ ساخت‌یافته درخواست/پاسخ
        - نگاشت خطاها به استثناهای دامنه
        - مدیریت سشن با Connection Pooling
        - پشتیبانی async/await مناسب UI غیرمسدودکننده
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        use_mock: bool = True,
        timeout: int = 30,
        max_retries: int = 3,
        *,
        config: Optional[APIConfig] = None,
        log_requests: Optional[bool] = None,
    ) -> None:
        self.config = config or APIConfig(
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            use_mock=use_mock,
        )
        if log_requests is not None:
            self.config.log_requests = log_requests

        self._logger = _get_logger()
        self._session: Optional[aiohttp.ClientSession] = None

    # ---------------- context management ----------------
    async def __aenter__(self) -> "APIClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        await self.close()

    async def close(self) -> None:
        """بستن سشن شبکه (در حالت Real)."""

        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    # ---------------- properties ----------------
    @property
    def use_mock(self) -> bool:
        return self.config.use_mock

    @use_mock.setter
    def use_mock(self, value: bool) -> None:
        self.config.use_mock = bool(value)

    # ---------------- public API ----------------
    async def get_students(
        self,
        filters: Optional[Dict] = None,
        date_range: Optional[tuple] = None,
        pagination: Optional[Dict[str, int]] = None,
    ) -> List[StudentDTO]:
        """دریافت لیست دانش‌آموزان.

        Args:
            filters: فیلترهای اختیاری مانند gender، center، level، ...

        Returns:
            لیست `StudentDTO`.
        """

        if self.use_mock:
            merged = dict(filters or {})
            if date_range:
                merged["created_at__gte"] = date_range[0].isoformat()
                merged["created_at__lte"] = date_range[1].isoformat()
            # pagination ignored for mock list API; use paginated method instead
            return await mock_backend.get_students(merged)

        params: Dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)
        if date_range:
            # also include in top-level for backend convenience
            if "filters" not in params:
                params["filters"] = json.dumps({}, ensure_ascii=False)
            # augment filters object
            fdict = json.loads(params["filters"]) if isinstance(params.get("filters"), str) else {}
            fdict["created_at__gte"] = date_range[0].isoformat()
            fdict["created_at__lte"] = date_range[1].isoformat()
            params["filters"] = json.dumps(fdict, ensure_ascii=False)
        if pagination:
            # allow backend to use page/page_size
            fdict = json.loads(params["filters"]) if isinstance(params.get("filters"), str) else {}
            fdict.update(pagination)
            params["filters"] = json.dumps(fdict, ensure_ascii=False)
        data = await self._request("GET", "/api/v1/students", params=params)
        students: List[StudentDTO] = []
        for item in data:
            if isinstance(item, StudentDTO):
                students.append(item)
            elif isinstance(item, dict):
                try:
                    students.append(StudentDTO(**item))
                except Exception:
                    students.append(migrate_student_dto(item))
        return students

    async def get_students_paginated(self, filters: Optional[Dict] = None, date_range: Optional[tuple] = None) -> Dict:
        """دریافت لیست صفحه‌بندی‌شده دانش‌آموزان.

        در حالت Mock صفحه‌بندی واقعی انجام می‌شود. در حالت Real بسته به سرور،
        همان پارامترها ارسال می‌گردد و پاسخ باید شامل total_count باشد.
        """
        if self.use_mock:
            merged = dict(filters or {})
            if date_range:
                merged["created_at__gte"] = date_range[0].isoformat()
                merged["created_at__lte"] = date_range[1].isoformat()
            return await mock_backend.get_students_paginated(merged)

        params: Dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)
        if date_range:
            fdict = json.loads(params["filters"]) if isinstance(params.get("filters"), str) else {}
            fdict["created_at__gte"] = date_range[0].isoformat()
            fdict["created_at__lte"] = date_range[1].isoformat()
            params["filters"] = json.dumps(fdict, ensure_ascii=False)
        data = await self._request("GET", "/api/v1/students", params=params)
        # انتظار: {"students": [...], "total_count": N}
        if isinstance(data, dict) and "students" in data:
            items = []
            for it in data.get("students", []):
                if isinstance(it, StudentDTO):
                    items.append(it)
                elif isinstance(it, dict):
                    try:
                        items.append(StudentDTO(**it))
                    except Exception:
                        items.append(migrate_student_dto(it))
            return {"students": items, "total_count": int(data.get("total_count", len(items)))}
        # fallback if server returned list
        if isinstance(data, list):
            items = []
            for it in data:
                if isinstance(it, dict):
                    try:
                        items.append(StudentDTO(**it))
                    except Exception:
                        items.append(migrate_student_dto(it))
            return {"students": items, "total_count": len(items)}
        return {"students": [], "total_count": 0}

    async def get_mentors(self, active_only: bool = True) -> List[MentorDTO]:
        """دریافت لیست منتورها.

        Args:
            active_only: فقط منتورهای فعال.
        Returns:
            لیست `MentorDTO`.
        """

        if self.use_mock:
            return await mock_backend.get_mentors(active_only)

        params = {"active": str(active_only).lower()}
        data = await self._request("GET", "/api/v1/mentors", params=params)
        return [MentorDTO(**item) for item in data]

    async def create_allocation(self, student_id: int, mentor_id: int) -> AllocationDTO:
        """ایجاد تخصیص دانش‌آموز به منتور.

        Args:
            student_id: شناسه دانش‌آموز.
            mentor_id: شناسه منتور.

        Returns:
            شیء `AllocationDTO`.
        """

        if self.use_mock:
            return await mock_backend.create_allocation(student_id, mentor_id)

        payload = {"student_id": student_id, "mentor_id": mentor_id}
        data = await self._request("POST", "/api/v1/allocations", json=payload)
        return AllocationDTO(**data)

    async def get_dashboard_stats(self) -> DashboardStatsDTO:
        """دریافت آمار داشبورد."""

        if self.use_mock:
            return await mock_backend.get_dashboard_stats()

        data = await self._request("GET", "/api/v1/dashboard/stats")
        return DashboardStatsDTO(**data)

    async def get_next_counter(self, gender: int) -> str:
        """دریافت شمارنده بعدی بر اساس جنسیت."""

        if self.use_mock:
            return await mock_backend.get_next_counter(gender)

        data = await self._request("GET", f"/api/v1/counters/next/{int(gender)}")
        # فرض: پاسخ مانند {"counter": "243731234"}
        if isinstance(data, dict) and "counter" in data:
            return str(data["counter"])  # type: ignore[return-value]
        if isinstance(data, str):
            return data
        raise APIException("ساختار پاسخ شمارنده نامعتبر است.")

    async def health_check(self) -> bool:
        """بررسی سلامت سرویس.

        در حالت Real یکی از اندپوینت‌ها فراخوانی می‌شود و موفقیت ۲۰۰ ملاک است.
        """

        if self.use_mock:
            return await mock_backend.health_check()
        try:
            await self._request("GET", "/api/v1/dashboard/stats", expect_json=False)
            return True
        except APIException:
            return False

    async def create_student(self, student_data: Dict[str, Any]) -> StudentDTO:
        """افزودن دانش‌آموز جدید."""
        if self.use_mock:
            return await mock_backend.create_student(student_data)
        # در حالت Real، نیازمند اندپوینت واقعی هستیم
        data = await self._request("POST", "/api/v1/students", json=student_data)
        try:
            return StudentDTO(**data)
        except Exception:
            return migrate_student_dto(data)

    async def update_student(self, student_id: int, student_data: Dict[str, Any]) -> StudentDTO:
        """به‌روزرسانی دانش‌آموز."""
        if self.use_mock:
            return await mock_backend.update_student(student_id, student_data)
        data = await self._request("PUT", f"/api/v1/students/{student_id}", json=student_data)
        try:
            return StudentDTO(**data)
        except Exception:
            return migrate_student_dto(data)

    async def delete_student(self, student_id: int) -> bool:
        """حذف دانش‌آموز."""
        if self.use_mock:
            return await mock_backend.delete_student(student_id)
        await self._request("DELETE", f"/api/v1/students/{student_id}", expect_json=False)
        return True

    # ---------------- internals ----------------
    async def _ensure_session(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            connector = aiohttp.TCPConnector(limit=100, enable_cleanup_closed=True)
            self._session = aiohttp.ClientSession(
                base_url=self.config.base_url,
                timeout=timeout,
                connector=connector,
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        expect_json: bool = True,
    ) -> Any:
        await self._ensure_session()
session = self._session
        if session is None:
            message = "نشست HTTP برای برقراری ارتباط با سرور ایجاد نشد."
            self._logger.error(message)
            raise RuntimeError(message)

        attempt = 0
        delay = self.config.retry_delay
        url = path
        last_exc: Optional[Exception] = None

        while attempt <= self.config.max_retries:
            attempt += 1
            start = time.perf_counter()
            try:
                async with session.request(method, url, params=params, json=json) as resp:
                    elapsed = round((time.perf_counter() - start) * 1000)
                    status = resp.status
                    text = await resp.text()
                    if self.config.log_requests:
                        self._logger.info(
                            "HTTP %s %s status=%s elapsed_ms=%s mock=%s params=%s payload=%s",
                            method,
                            url,
                            status,
                            elapsed,
                            self.use_mock,
                            params,
                            json,
                        )

                    # نگاشت خطاها
                    if 200 <= status < 300:
                        if expect_json:
                            try:
                                return await resp.json(content_type=None)
                            except Exception:
                                # ممکن است متنی باشد
                                return text
                        return text

                    if status == 400:
                        raise ValidationException(text)
                    if status in (401, 403, 404):
                        raise APIException(text)
                    if status in (409, 422):
                        raise BusinessRuleException(text)
                    if 500 <= status < 600:
                        raise NetworkException(f"Server error {status}: {text}")

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if self.config.log_requests:
                    self._logger.warning(
                        "request_error attempt=%s method=%s path=%s error=%s",
                        attempt,
                        method,
                        path,
                        repr(exc),
                    )
                # fallthrough to retry
            except (ValidationException, BusinessRuleException, APIException):
                # خطاهای غیرقابل بازیابی
                raise

            # Retry with exponential backoff
            if attempt <= self.config.max_retries:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                break

        if last_exc:
            raise NetworkException(str(last_exc))
        raise APIException("درخواست ناموفق بود و به سقف تلاش رسید.")
