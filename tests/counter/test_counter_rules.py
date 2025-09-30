from src.domain.counter.value_objects import Counter
from src.domain.shared.types import Gender
from src.phase2_counter_service.validation import COUNTER_PATTERN, COUNTER_PREFIX
from src.shared.counter_rules import COUNTER_PREFIX_MAP, COUNTER_REGEX, gender_prefix


def test_gender_prefix_map() -> None:
    assert COUNTER_PREFIX_MAP == {0: "373", 1: "357"}
    assert COUNTER_PREFIX == COUNTER_PREFIX_MAP
    assert gender_prefix(0) == "373"
    assert gender_prefix(1) == "357"
    assert Gender.male.counter_code == "373"
    assert Gender.female.counter_code == "357"


def test_counter_regex_accepts_expected_patterns() -> None:
    for seed in ("023731234", "993571111"):
        assert COUNTER_PATTERN.fullmatch(seed)
        assert COUNTER_REGEX.fullmatch(seed)
    assert COUNTER_PATTERN.fullmatch("123670001") is None
    assert COUNTER_REGEX.fullmatch("123670001") is None


def test_counter_build_uses_gender_prefix() -> None:
    counter = Counter.build("25", Gender.female, 42)
    assert counter.value == "25" + COUNTER_PREFIX_MAP[1] + "0042"
