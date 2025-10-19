from __future__ import annotations

from tools import reqs_doctor


def test_test_file_includes_only_runtime_and_dev(doctor_env):
    repo = doctor_env.make_namespace("layout")
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.txt").write_text("numpy==1.26.4\npytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-dev.txt").write_text("pytest==7.3.1\ncoverage==7.2\n", encoding="utf-8")
    (repo / "requirements-test.txt").write_text(
        "-r requirements.txt\npytest==7.3.1\ncoverage==7.2\n", encoding="utf-8"
    )
    (repo / "requirements-security.txt").write_text(
        "pip-audit==2.7.3\ncyclonedx-bom==3.2.0\npytest==7.3.1\n", encoding="utf-8"
    )
    (repo / "requirements-ml.txt").write_text("pandas==1.5.0\n", encoding="utf-8")
    (repo / "requirements-advanced.txt").write_text("# advanced\n", encoding="utf-8")

    result = doctor_env.run_with_retry(["fix", "--repo", str(repo), "--apply"])
    assert result.exit_code == 0, doctor_env.debug()
    test_lines = (repo / "requirements-test.txt").read_text(encoding="utf-8").strip().splitlines()
    assert test_lines == ["-r requirements.txt", "-r requirements-dev.txt"], doctor_env.debug()
    runtime_text = (repo / "requirements.txt").read_text(encoding="utf-8")
    assert "pip-audit" not in runtime_text
    security_text = (repo / "requirements-security.txt").read_text(encoding="utf-8")
    assert "pip-audit" in security_text
    assert "cyclonedx-bom>=7.1,<8" in security_text
