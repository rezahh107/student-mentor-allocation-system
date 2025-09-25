from __future__ import annotations

import asyncio
import pytest

from src.api.exceptions import ValidationException
from src.api.mock_data import MockBackend


def test_reject_invalid_grade_level_on_create():
    backend = MockBackend()
    async def run() -> None:
        await backend.create_student({
            "first_name": "علی",
            "last_name": "احمدی",
            "gender": 1,
            "center": 1,
            "education_status": 1,
            "grade_level": "invalid_group",
        })

    with pytest.raises(ValidationException):
        asyncio.run(run())


def test_reject_invalid_grade_level_on_update():
    backend = MockBackend()
    s = backend._students[0]
    async def run() -> None:
        await backend.update_student(s.student_id, {"grade_level": "UNKNOWN"})

    with pytest.raises(ValidationException):
        asyncio.run(run())

