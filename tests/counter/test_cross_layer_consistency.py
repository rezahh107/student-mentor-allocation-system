from src.domain.shared.types import Gender
from src.phase2_counter_service.validation import COUNTER_PREFIX
from src.shared.counter_rules import COUNTER_PREFIX_MAP


def test_domain_vs_service_prefix() -> None:
    assert COUNTER_PREFIX == COUNTER_PREFIX_MAP
    assert Gender.male.counter_code == COUNTER_PREFIX_MAP[Gender.male.value]
    assert Gender.female.counter_code == COUNTER_PREFIX_MAP[Gender.female.value]
