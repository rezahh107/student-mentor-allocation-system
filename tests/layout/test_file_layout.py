from __future__ import annotations

from tools import reqs_doctor


def test_test_file_includes_only_runtime_and_dev(doctor_env):
    repo = doctor_env.make_namespace("layout")
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.in").write_text("numpy==1.26.4\npytest==8.4.2\n", encoding="utf-8")
    (repo / "requirements-dev.in").write_text("-r requirements.in\npytest==8.4.2\ncoverage==7.4\n", encoding="utf-8")
    (repo / "requirements-test.in").write_text(
        "-r requirements.in\npytest==8.4.2\ncoverage==7.4\n", encoding="utf-8"
    )
    (repo / "requirements-security.in").write_text(
        "pip-audit==2.7.3\npytest==8.4.2\n", encoding="utf-8"
    )
    (repo / "requirements-ml.txt").write_text("pandas==1.5.0\n", encoding="utf-8")
    (repo / "requirements-advanced.txt").write_text("# advanced\n", encoding="utf-8")

    result = doctor_env.run_with_retry(["fix", "--repo", str(repo), "--apply"])
    assert result.exit_code == 0, doctor_env.debug()
    test_lines = (repo / "requirements-test.in").read_text(encoding="utf-8").strip().splitlines()
    assert test_lines == ["-r requirements.in", "-r requirements-dev.in"], doctor_env.debug()
    runtime_text = (repo / "requirements.in").read_text(encoding="utf-8")
    assert "pip-audit" not in runtime_text
    security_text = (repo / "requirements-security.in").read_text(encoding="utf-8")
    assert "pip-audit" in security_text
