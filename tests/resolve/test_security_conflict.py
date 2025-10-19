from __future__ import annotations

def test_pip_audit_cyclonedx_policyA(doctor_env):
    repo = doctor_env.make_namespace("security")
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.txt").write_text("numpy==1.26.4\n", encoding="utf-8")
    (repo / "requirements-dev.txt").write_text("pytest==7.4.0\n", encoding="utf-8")
    (repo / "requirements-test.txt").write_text("-r requirements.txt\n", encoding="utf-8")
    (repo / "requirements-security.txt").write_text(
        "pip-audit==2.7.3\ncyclonedx-bom==3.2.0\ncyclonedx-python-lib==2.1.0\n",
        encoding="utf-8",
    )
    (repo / "requirements-ml.txt").write_text("pandas==1.5.0\n", encoding="utf-8")
    (repo / "requirements-advanced.txt").write_text("# advanced\n", encoding="utf-8")

    result = doctor_env.run_with_retry(["fix", "--repo", str(repo), "--apply"])
    assert "سیاست A" in result.output
    security_text = (repo / "requirements-security.txt").read_text(encoding="utf-8")
    assert "cyclonedx-bom>=7.1,<8" in security_text
    assert "pip-audit==2.7.3" in security_text
