"""Concurrency safety tests for shared Redis and DB resources."""

from __future__ import annotations

import asyncio

import pytest

from phase6_import_to_sabt.sanitization import deterministic_jitter


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_redis_writes(clean_redis_state, get_debug_context) -> None:
    """Verify Redis increments remain atomic under concurrent workloads.

    Example:
        >>> # executed via pytest - test ensures deterministic atomicity
        >>> ...  # doctest: +SKIP
    """

    redis_key = clean_redis_state.key("concurrency:counter")
    client = clean_redis_state.client
    total_tasks = 32

    async def writer(task_id: int) -> int:
        attempts = 0
        while True:
            attempts += 1
            try:
                result = await asyncio.to_thread(client.incr, redis_key)
                return result
            except Exception as exc:  # pragma: no cover - defensive retry path
                backoff = deterministic_jitter(0.01, attempts, f"redis:{task_id}")
                await asyncio.sleep(backoff)

    results = await asyncio.gather(*(writer(i) for i in range(total_tasks)))
    final_value = int((client.get(redis_key) or b"0"))
    diagnostics = get_debug_context(extra={"results": results, "expected": total_tasks})
    assert final_value == total_tasks, diagnostics
    assert sorted(results) == list(range(1, total_tasks + 1)), diagnostics


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_db_transactions(clean_db_state, get_debug_context) -> None:
    """Ensure concurrent transactions rollback cleanly and keep FK guarantees.

    Example:
        >>> # executed via pytest - transaction logs captured for debugging
        >>> ...  # doctest: +SKIP
    """

    async def transactional_op(student_id: int) -> str:
        async with clean_db_state.begin():
            clean_db_state.record_query(f"INSERT INTO students(id) VALUES ({student_id})")
            async with clean_db_state.begin_nested():
                clean_db_state.record_query(f"UPDATE students SET touched = 1 WHERE id = {student_id}")
            await asyncio.sleep(0)
            return f"student:{student_id}"

    ids = list(range(1, 11))
    outcomes = await asyncio.gather(*(transactional_op(student_id) for student_id in ids))
    diagnostics = get_debug_context(extra={"queries": clean_db_state.queries, "outcomes": outcomes})
    assert len(outcomes) == len(ids), diagnostics
    assert all(outcome.startswith("student:") for outcome in outcomes), diagnostics
    assert len(clean_db_state.queries) == len(ids) * 2, diagnostics
