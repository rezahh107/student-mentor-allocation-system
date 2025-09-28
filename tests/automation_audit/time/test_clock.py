from automation_audit.providers.academic_year import AcademicYearProvider


def test_clock_freeze(frozen_clock):
    provider = AcademicYearProvider(clock=frozen_clock)
    assert provider.year_code() == str(int(frozen_clock()))[-2:]
