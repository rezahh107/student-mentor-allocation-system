from __future__ import annotations

import json


def test_unified_diff_and_json_plan(doctor_env):
    repo = doctor_env.make_namespace("plan")
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.txt").write_text("numpy==1.26.4\npytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-dev.txt").write_text("pytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-test.txt").write_text("-r requirements.txt\npytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-security.txt").write_text("pip-audit==2.7.3\ncyclonedx-bom==3.2.0\n", encoding="utf-8")
    (repo / "requirements-ml.txt").write_text("pandas==1.5.0\n", encoding="utf-8")
    (repo / "requirements-advanced.txt").write_text("# advanced\n", encoding="utf-8")

    result = doctor_env.run_with_retry(["plan", "--repo", str(repo)])
    output = result.output
    json_start = output.find("{\n")
    plan_json = json.loads(output[json_start:])
    assert plan_json["messages"]
    diff = output[:json_start]
    assert "requirements-test.txt" in diff
    assert 'numpy>=2.1 ; python_version >= "3.13"' in output
