from src.phase2_counter_service.validation import COUNTER_PATTERN, COUNTER_PREFIX


def test_regex_and_prefixes() -> None:
    assert COUNTER_PREFIX == {0: "373", 1: "357"}
    assert COUNTER_PATTERN.fullmatch("023731234")
    assert COUNTER_PATTERN.fullmatch("023571234")
    assert COUNTER_PATTERN.fullmatch("123670001") is None
