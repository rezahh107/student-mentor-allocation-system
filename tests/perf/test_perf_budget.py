from __future__ import annotations

import time
import tracemalloc

from tools.reqs_doctor.planner import plan as build_plan


def test_planner_perf_budget(doctor_env):
    repo = doctor_env.make_namespace("perf")
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    (repo / "requirements-dev.txt").write_text("pytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-test.txt").write_text("-r requirements.txt\npytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-security.txt").write_text("pip-audit==2.7.3\ncyclonedx-bom==3.2.0\n", encoding="utf-8")
    (repo / "requirements-ml.txt").write_text("pandas==1.5.0\n", encoding="utf-8")
    (repo / "requirements-advanced.txt").write_text("# advanced\n", encoding="utf-8")
    tracemalloc.start()
    start = time.perf_counter()
    result = build_plan(repo, policy="A")
    duration = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert duration <= 0.2, f"Duration {duration}; debug={doctor_env.debug()}"
    assert peak < 200 * 1024 * 1024
    assert result.messages
