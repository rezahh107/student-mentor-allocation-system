import pytest

from automation_audit.counter import COUNTER_RE, CounterBuilder
from automation_audit.providers.academic_year import AcademicYearProvider


def test_counter_regex(frozen_clock):
    builder = CounterBuilder(AcademicYearProvider(clock=frozen_clock))
    value = builder.build(0, 42)
    assert COUNTER_RE.fullmatch(value)
    with pytest.raises(KeyError):
        builder.build(9, 1)
