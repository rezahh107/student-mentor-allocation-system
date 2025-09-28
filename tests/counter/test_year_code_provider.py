import pytest

from src.phase2_counter_service.academic_year import AcademicYearProvider


def test_year_code_from_provider_no_wall_clock() -> None:
    forbidden = {"now", "utcnow", "today"}
    names = set(AcademicYearProvider.code_for.__code__.co_names)
    assert names.isdisjoint(forbidden)
    provider = AcademicYearProvider({"1402": "02"})
    assert provider.code_for("۱۴۰۲") == "02"
    assert provider.code_for("1403") == "03"


@pytest.mark.parametrize("value", [None, "", "abcd", "۱۴"])
def test_year_code_invalid_inputs(value) -> None:
    provider = AcademicYearProvider({})
    with pytest.raises(ValueError):
        provider.code_for(value)
