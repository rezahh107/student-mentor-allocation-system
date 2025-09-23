from __future__ import annotations

import pytest

from src.api.mock_data import MockBackend
from src.api.exceptions import ValidationException


@pytest.mark.asyncio
async def test_reject_invalid_grade_level_on_create():
    backend = MockBackend()
    with pytest.raises(ValidationException):
        await backend.create_student({
            "first_name": "علی",
            "last_name": "احمدی",
            "gender": 1,
            "center": 1,
            "education_status": 1,
            "grade_level": "invalid_group",
        })


@pytest.mark.asyncio
async def test_reject_invalid_grade_level_on_update():
    backend = MockBackend()
    s = backend._students[0]
    with pytest.raises(ValidationException):
        await backend.update_student(s.student_id, {"grade_level": "UNKNOWN"})

