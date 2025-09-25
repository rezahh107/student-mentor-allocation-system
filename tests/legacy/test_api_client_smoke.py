import asyncio
from datetime import date, datetime, timezone
from typing import Any

import pytest

import aiohttp

from src.api.client import APIClient, LEGACY_IMPORT_DIAGNOSTIC
from src.api.exceptions import (
    APIException,
    BusinessRuleException,
    NetworkException,
    ValidationException,
)


def test_import_diagnostic_contains_code() -> None:
    assert "LEGACY_IMPORT_ERROR_FIXED" in LEGACY_IMPORT_DIAGNOSTIC


def test_api_client_mock_roundtrip() -> None:
    async def scenario() -> None:
        client = APIClient(use_mock=True)
        students = await client.get_students()
        assert students, "بک‌اند موک باید حداقل یک دانش‌آموز بازگرداند"
        mentors = await client.get_mentors()
        assert mentors, "بک‌اند موک باید حداقل یک منتور بازگرداند"
        allocation = None
        chosen_student = None
        for student in students:
            for mentor in mentors:
                try:
                    allocation = await client.create_allocation(student.student_id, mentor.id)
                except BusinessRuleException:
                    continue
                else:
                    chosen_student = student
                    break
            if allocation is not None:
                break
        assert allocation is not None, "باید یک تخصیص موک معتبر یافت شود"
        assert chosen_student is not None
        assert allocation.student_id == chosen_student.student_id
        stats = await client.get_dashboard_stats()
        assert stats.total_students >= 0
        counter = await client.get_next_counter(gender=1)
        assert counter
        created = await client.create_student(
            {
                "first_name": "سارا",
                "last_name": "تست",
                "gender": 0,
                "grade_level": "konkoori",
                "education_status": 1,
            }
        )
        updated = await client.update_student(created.student_id, {"first_name": "زهرا"})
        assert updated.first_name == "زهرا"
        assert await client.delete_student(created.student_id) is True
        assert await client.health_check() is True
        await client.close()

    asyncio.run(scenario())


def test_api_client_real_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        client = APIClient(use_mock=False)

        base_payload = {
            "gender": 1,
            "education_status": 1,
            "registration_status": 1,
            "center": 1,
            "grade_level": "konkoori",
            "school_type": "normal",
            "school_code": "SCH-1",
            "national_code": "1234567890",
            "phone": "09120000000",
            "birth_date": date(2004, 1, 1),
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "counter": "2400010001",
        }

        async def fake_request(method: str, path: str, **kwargs: Any):
            if path == "/api/v1/students" and method == "GET":
                if kwargs.get("params"):
                    return {
                        "students": [
                            {
                                **base_payload,
                                "student_id": 11,
                                "first_name": "سارا",
                                "last_name": "نمونه",
                            }
                        ],
                        "total_count": 1,
                    }
                return [
                    {
                        **base_payload,
                        "student_id": 10,
                        "first_name": "علی",
                        "last_name": "تست",
                    },
                    {
                        **base_payload,
                        "id": 9,
                        "name": "مینا رضایی",
                        "registration_type": 1,
                        "center": 2,
                    },
                ]
            if path == "/api/v1/mentors":
                return [
                    {
                        "id": 1,
                        "name": "Mentor",
                        "gender": 0,
                        "capacity": 1,
                        "current_load": 0,
                        "allowed_groups": [],
                        "allowed_centers": [],
                        "is_school_mentor": False,
                    }
                ]
            if path == "/api/v1/allocations":
                return {
                    "id": 99,
                    "student_id": 10,
                    "mentor_id": 1,
                    "status": "OK",
                    "created_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
                    "notes": "",
                }
            if path == "/api/v1/dashboard/stats":
                return {
                    "total_students": 1,
                    "total_mentors": 1,
                    "total_allocations": 1,
                    "allocation_success_rate": 1.0,
                    "capacity_utilization": 0.5,
                    "status_breakdown": {"OK": 1},
                }
            if path.startswith("/api/v1/counters/next/"):
                return {"counter": "99000001"}
            if path == "/api/v1/students" and method == "POST":
                return {**base_payload, "student_id": 15, "first_name": "زهرا", "last_name": "نمونه"}
            if path.startswith("/api/v1/students/") and method == "PUT":
                return {**base_payload, "student_id": 15, "first_name": "زهرا", "last_name": "به‌روز"}
            if path.startswith("/api/v1/students/") and method == "DELETE":
                return "deleted"
            return {}

        async def fake_health_request(method: str, path: str, **kwargs: Any):
            if path == "/api/v1/dashboard/stats" and kwargs.get("expect_json") is False:
                return "OK"
            return await fake_request(method, path, **kwargs)

        async def fake_ensure() -> None:
            return None

        monkeypatch.setattr(client, "_ensure_session", fake_ensure, raising=False)
        monkeypatch.setattr(client, "_request", fake_health_request, raising=False)

        students = await client.get_students()
        assert len(students) == 2
        assert students[1].first_name == "مینا"
        paginated = await client.get_students_paginated(filters={"status": "active"})
        assert paginated["total_count"] == 1
        mentors = await client.get_mentors()
        assert mentors[0].id == 1
        allocation = await client.create_allocation(10, 1)
        assert allocation.mentor_id == 1
        stats = await client.get_dashboard_stats()
        assert stats.total_students == 1
        counter = await client.get_next_counter(gender=1)
        assert counter == "99000001"
        assert await client.health_check() is True
        created = await client.create_student({"first_name": "زهرا"})
        assert created.first_name == "زهرا"
        updated = await client.update_student(15, {"first_name": "زهرا"})
        assert updated.last_name == "به‌روز"
        assert await client.delete_student(15) is True
        await client.close()

    asyncio.run(scenario())


def test_request_without_session_raises_persian_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client = APIClient(use_mock=False)

    async def fake_ensure() -> None:  # pragma: no cover - async helper for monkeypatch
        client._session = None

    monkeypatch.setattr(client, "_ensure_session", fake_ensure)

    async def scenario() -> None:
        with pytest.raises(RuntimeError) as excinfo:
            await client._request("GET", "/healthz")
        assert "نشست HTTP" in str(excinfo.value)

    asyncio.run(scenario())
    asyncio.run(client.close())


def test_request_success_and_network_error(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    class _FakeResponse:
        def __init__(self, status: int, payload: Any, text: str) -> None:
            self.status = status
            self._payload = payload
            self._text = text

        async def text(self) -> str:
            return self._text

        async def json(self, *, content_type: Any = None) -> Any:  # noqa: ARG002
            if isinstance(self._payload, Exception):
                raise self._payload
            return self._payload

    class _Context:
        def __init__(self, response: _FakeResponse) -> None:
            self._response = response

        async def __aenter__(self) -> _FakeResponse:
            return self._response

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

    class _FakeSession:
        def __init__(self, responses: list[_FakeResponse]) -> None:
            self._responses = responses
            self.closed = False

        def request(self, *_args: Any, **_kwargs: Any) -> _Context:
            return _Context(self._responses.pop(0))

        async def close(self) -> None:
            self.closed = True

    async def scenario() -> None:
        client = APIClient(use_mock=False, log_requests=True)
        client.config.max_retries = 0

        success_response = _FakeResponse(200, {"ok": True}, "{}")
        error_response = _FakeResponse(500, {}, "boom")
        session = _FakeSession([success_response])

        async def fake_ensure() -> None:
            return None

        monkeypatch.setattr(client, "_ensure_session", fake_ensure, raising=False)
        client._session = session  # type: ignore[assignment]

        caplog.set_level("INFO")
        result = await client._request("GET", "/api/v1/test")
        assert result == {"ok": True}
        assert any("HTTP GET" in record.getMessage() for record in caplog.records)

        session_error = _FakeSession([error_response])
        client._session = session_error  # type: ignore[assignment]
        client.config.log_requests = False
        with pytest.raises(NetworkException):
            await client._request("GET", "/api/v1/test")

        for status, exc_type in (
            (400, ValidationException),
            (404, APIException),
            (409, BusinessRuleException),
        ):
            client._session = _FakeSession([_FakeResponse(status, {}, "err")])  # type: ignore[assignment]
            with pytest.raises(exc_type):
                await client._request("GET", "/api/v1/test")

        class _ClientErrorSession:
            def __init__(self) -> None:
                self.closed = False

            def request(self, *_args: Any, **_kwargs: Any) -> Any:
                raise aiohttp.ClientError("boom")

            async def close(self) -> None:
                self.closed = True

        client.config.max_retries = 1
        client.config.log_requests = True

        async def fake_sleep(_delay: float) -> None:  # noqa: D401
            return None

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        client._session = _ClientErrorSession()  # type: ignore[assignment]
        with pytest.raises(NetworkException):
            await client._request("GET", "/api/v1/test")

        await client.close()

    asyncio.run(scenario())


def test_ensure_session_creates_aiohttp_session() -> None:
    async def scenario() -> None:
        client = APIClient(use_mock=False)
        await client._ensure_session()
        assert client._session is not None and not client._session.closed
        await client.close()

    asyncio.run(scenario())


def test_async_context_manager_and_toggle() -> None:
    async def scenario() -> None:
        async with APIClient(use_mock=True) as client:
            assert client._session is not None
            client.use_mock = False
            assert client.use_mock is False
        assert client._session is None

    asyncio.run(scenario())


def test_mock_students_handles_date_range() -> None:
    async def scenario() -> None:
        client = APIClient(use_mock=True)
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, tzinfo=timezone.utc)
        students = await client.get_students(filters={"status": "active"}, date_range=(start, end))
        assert isinstance(students, list)
        paginated = await client.get_students_paginated(filters={}, date_range=(start, end))
        assert "total_count" in paginated
        await client.close()

    asyncio.run(scenario())
