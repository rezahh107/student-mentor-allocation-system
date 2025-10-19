from __future__ import annotations
from tools import reqs_doctor


def test_missing_agents_md_fails_persian(doctor_env):
    repo = doctor_env.make_namespace("missing_agents")
    for name in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "requirements-security.txt",
        "requirements-ml.txt",
        "requirements-advanced.txt",
    ):
        (repo / name).write_text("", encoding="utf-8")
    result = None
    for attempt in range(1, 3):
        result = doctor_env.runner.invoke(reqs_doctor.app, ["scan", "--repo", str(repo)])
        if result.exit_code != 0:
            break
        doctor_env.clock.tick(seconds=attempt * 0.05)
    assert result is not None
    assert result.exit_code != 0, doctor_env.debug()
    assert "AGENTS.md" in result.output
    assert "پروندهٔ AGENTS.md" in result.output
