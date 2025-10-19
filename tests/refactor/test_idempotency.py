from __future__ import annotations

from tools.refactor_imports import IdempotencyStore, IDEMPOTENCY_TTL_SECONDS


class Clock:
    def __init__(self) -> None:
        self._value = 0

    def now(self) -> int:
        return self._value

    def advance(self, seconds: int) -> None:
        self._value += seconds


def test_ttl_get_open_post_closed_concurrency() -> None:
    clock = Clock()
    store = IdempotencyStore(clock=clock.now)
    key = "ns:apply:rid"
    assert store.check_and_set(key, "cli", method="POST")
    assert not store.check_and_set(key, "cli", method="POST")
    assert store.check_and_set(key, "cli", method="GET")
    clock.advance(IDEMPOTENCY_TTL_SECONDS + 1)
    assert store.check_and_set(key, "cli", method="POST")
