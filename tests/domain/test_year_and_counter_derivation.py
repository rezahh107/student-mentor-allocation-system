from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from sma.phase2_counter_service.academic_year import AcademicYearProvider
from sma.phase6_import_to_sabt.models import COUNTER_PREFIX
from sma.shared.counter_rules import gender_prefix


@pytest.fixture(name="clean_state")
def fixture_clean_state(tmp_path: Path) -> Path:
    sandbox = tmp_path / uuid.uuid4().hex
    sandbox.mkdir()
    yield sandbox
    for child in sandbox.iterdir():
        child.unlink()
    sandbox.rmdir()


def test_counter_prefix_and_year_code(clean_state: Path) -> None:
    provider = AcademicYearProvider({1402: "02", 1403: "03"})
    assert provider.code_for(1402) == "02"
    assert provider.code_for(1403) == "03"
    assert COUNTER_PREFIX[0] == "373"
    assert COUNTER_PREFIX[1] == "357"
    assert gender_prefix(0) == "373"
    assert gender_prefix(1) == "357"
