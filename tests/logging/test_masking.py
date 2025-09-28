from __future__ import annotations

import asyncio
import json
import logging
from hashlib import blake2s

from src.hardened_api.redis_support import RedisExecutor, RedisNamespaces, RedisRetryConfig
from src.phase2_counter_service.academic_year import AcademicYearProvider
from src.phase2_counter_service.counter_runtime import CounterRuntime
from src.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics


class _SimpleRedis:
    async def eval(self, script: str, numkeys: int, *args):
        argv = args[numkeys:]
        year_code = argv[1]
        prefix = argv[2]
        counter = f"{year_code}{prefix}0001"
        return json.dumps({"status": "NEW", "counter": counter, "serial": "0001"})

    async def get(self, name: str):
        return None


def test_no_raw_pii_in_logs(caplog) -> None:
    async def _run() -> None:
        executor = RedisExecutor(
            config=RedisRetryConfig(attempts=1, base_delay=0.0, max_delay=0.0, jitter=0.0),
            namespace="log-mask",
        )
        runtime = CounterRuntime(
            redis=_SimpleRedis(),
            namespaces=RedisNamespaces("masking"),
            executor=executor,
            metrics=CounterRuntimeMetrics(),
            year_provider=AcademicYearProvider({"1402": "02"}),
            hash_salt="mask",
        )
        payload = {"year": "1402", "gender": 1, "center": 0, "student_id": "MASK-۹۹۹۹"}
        with caplog.at_level(logging.INFO):
            await runtime.allocate(payload, correlation_id="masking")

        hashed = blake2s(key=b"mask", digest_size=16)
        hashed.update("MASK-۹۹۹۹".encode("utf-8"))
        digest = hashed.hexdigest()
        assert digest in caplog.text
        assert "MASK-۹۹۹۹" not in caplog.text

    asyncio.run(_run())
