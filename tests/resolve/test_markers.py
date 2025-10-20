from __future__ import annotations

def test_numpy_pandas_markers_for_313(doctor_env):
    repo = doctor_env.make_namespace("markers")
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.in").write_text("numpy==1.26.4\n", encoding="utf-8")
    (repo / "requirements-dev.in").write_text("-r requirements.in\npytest==8.4.2\n", encoding="utf-8")
    (repo / "requirements-test.in").write_text("-r requirements.in\n", encoding="utf-8")
    (repo / "requirements-security.in").write_text("pip-audit==2.7.3\n", encoding="utf-8")
    (repo / "requirements-ml.txt").write_text("pandas==1.5.0\n", encoding="utf-8")
    (repo / "requirements-advanced.txt").write_text("# advanced\n", encoding="utf-8")

    doctor_env.run_with_retry(["fix", "--repo", str(repo), "--apply"])
    runtime_lines = (repo / "requirements.in").read_text(encoding="utf-8").strip().splitlines()
    assert 'numpy>=2.1 ; python_version >= "3.13"' in runtime_lines
    assert 'pandas>=2.2.3 ; python_version >= "3.13"' in runtime_lines
