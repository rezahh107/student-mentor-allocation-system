from __future__ import annotations

import concurrent.futures

from sma.repo_doctor.clock import tehran_clock
from sma.repo_doctor.idempotency import IdempotencyEnforcer
from sma.repo_doctor.retry import RetryPolicy


def test_only_one_succeeds(fake_redis) -> None:
    namespace = IdempotencyEnforcer.new_namespace()
    enforcer = IdempotencyEnforcer(
        redis=fake_redis,
        namespace=namespace,
        clock=tehran_clock(),
        retry=RetryPolicy(attempts=1),
    )

    def task() -> bool:
        return enforcer.acquire("req-123", {"rid": namespace})

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: task(), range(5)))

    assert sum(1 for result in results if result) == 1
    enforcer.release("req-123")
