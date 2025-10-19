from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools import reqs_doctor


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_plan_and_fix_on_fixture_repo(tmp_path):
    repo = tmp_path / "fixture_repo"
    repo.mkdir()

    _write(repo / "AGENTS.md", "# fixture\n")
    _write(
        repo / "requirements.txt",
        "pip-audit==2.7.3\npytest==7.2.0\nnumpy==1.26.0\npandas==1.5.3\n",
    )
    _write(repo / "requirements-dev.txt", "pytest==7.2.0\n")
    _write(repo / "requirements-security.txt", "cyclonedx-bom==3.2.0\n")
    _write(repo / "requirements-test.txt", "-r requirements.txt\npytest==7.2.0\n")
    _write(repo / "requirements-ml.txt", "pandas==1.5.3\n")
    _write(repo / "requirements-advanced.txt", "")

    runner = CliRunner()
    plan_result = runner.invoke(reqs_doctor.app, ["plan", "--repo", str(repo)])
    assert plan_result.exit_code == 0, plan_result.output
    assert "-r requirements-dev.txt" in plan_result.output

    scan_result = runner.invoke(reqs_doctor.app, ["scan", "--repo", str(repo)])
    assert scan_result.exit_code == 0, scan_result.output
    plan_data = json.loads(scan_result.output)
    assert plan_data["policy"].upper() == "A"
    assert any(action["file"].endswith("requirements-security.txt") for action in plan_data["actions"])

    fix_result = runner.invoke(reqs_doctor.app, ["fix", "--repo", str(repo), "--apply"])
    assert fix_result.exit_code == 0, fix_result.output

    runtime_text = (repo / "requirements.txt").read_text(encoding="utf-8")
    runtime_expected = next(
        action["updated_text"]
        for action in plan_data["actions"]
        if action["file"].endswith("requirements.txt")
    )
    assert runtime_text == runtime_expected
    test_lines = (repo / "requirements-test.txt").read_text(encoding="utf-8").splitlines()
    assert test_lines == ["-r requirements.txt", "-r requirements-dev.txt"]
    security_text = (repo / "requirements-security.txt").read_text(encoding="utf-8")
    assert "cyclonedx-bom>=7.1,<8" in security_text

    post_scan = runner.invoke(reqs_doctor.app, ["scan", "--repo", str(repo)])
    assert post_scan.exit_code == 0, post_scan.output
    post_plan = json.loads(post_scan.output)
    assert post_plan["actions"] == []
