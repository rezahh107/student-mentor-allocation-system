"""Regression tests for GitHub Actions workflow runner integration."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

WORKFLOW_PATH = Path(".github/workflows/api-hardening.yml")


def _flush_redis(redis_url: str) -> None:
    """Best-effort Redis cleanup to honor integration test contracts."""
    if not redis_url:
        return
    try:
        import redis  # type: ignore
    except Exception:
        return
    try:
        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            retry_on_timeout=False,
        )
        client.flushdb()
    except Exception:
        # The environment might not provide Redis; ignore cleanup failures.
        return


def _debug_context(namespace: str, redis_url: str, duration_ms: float, content: str) -> str:
    preview = "\n".join(content.splitlines()[:12])
    return (
        "--- DEBUG CONTEXT ---\n"
        f"namespace={namespace}\n"
        f"redis_url={redis_url or 'N/A'}\n"
        f"duration_ms={duration_ms:.2f}\n"
        f"preview=\n{preview}\n"
    )


@pytest.fixture
def clean_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Provide integration-aware cleanup semantics for workflow checks."""
    namespace = f"gha-ci-{uuid.uuid4().hex}"
    redis_url = os.environ.get("REDIS_URL", "")
    _flush_redis(redis_url)
    monkeypatch.setenv("CI_GHA_NAMESPACE", namespace)
    yield {"namespace": namespace, "redis_url": redis_url}
    _flush_redis(redis_url)


def test_api_hardening_workflow_uses_ci_runner(clean_state: dict[str, str]) -> None:
    """Verify workflow steps leverage the shared CI pytest runner across modes."""
    start = time.monotonic()
    content = ""
    last_error = ""
    for attempt in range(3):
        try:
            content = WORKFLOW_PATH.read_text(encoding="utf-8")
            break
        except FileNotFoundError as exc:
            last_error = str(exc)
            time.sleep(0.1 * (attempt + 1))
    else:
        duration_ms = (time.monotonic() - start) * 1000
        pytest.fail(
            "Workflow file missing after retries: "
            f"{last_error}\n{_debug_context(clean_state['namespace'], clean_state['redis_url'], duration_ms, content)}"
        )

    duration_ms = (time.monotonic() - start) * 1000
    assert "mode: [stub, redis]" in content, _debug_context(
        clean_state["namespace"], clean_state["redis_url"], duration_ms, content
    )
    assert "- name: Select mode env" in content, _debug_context(
        clean_state["namespace"], clean_state["redis_url"], duration_ms, content
    )
    assert "python tools/ci_pytest_runner.py" in content, _debug_context(
        clean_state["namespace"], clean_state["redis_url"], duration_ms, content
    )
    assert "pytest -q -k \"excel or admin" not in content, _debug_context(
        clean_state["namespace"], clean_state["redis_url"], duration_ms, content
    )
