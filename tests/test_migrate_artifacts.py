from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from tools.migrate_artifacts_v3_to_v4 import COMMENT_TEXT, HELPER_STEP_NAME

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "migrate_artifacts_v3_to_v4.py"


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(SCRIPT_PATH), *args, "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )


def write_workflow(tmp_path: Path, relative: str, content: str) -> Path:
    workflow_path = tmp_path / ".github" / "workflows" / relative
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(content)
    return workflow_path


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_single_file_upgrade(tmp_path: Path) -> None:
    workflow_content = """
name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Upload coverage
        uses: actions/upload-artifact@v3
        with:
          path: coverage/coverage.xml
          retention-days: 7
      - name: Download coverage
        uses: actions/download-artifact@v3
        with:
          path: ./artifacts
"""
    workflow_path = write_workflow(tmp_path, "ci.yml", workflow_content)

    result = run_cli(tmp_path, "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    updated = workflow_path.read_text()
    assert "actions/upload-artifact@v4" in updated
    assert "actions/download-artifact@v4" in updated
    assert "name: coverage.xml" in updated
    assert "name: artifacts" in updated
    assert COMMENT_TEXT in updated
    assert HELPER_STEP_NAME in updated
    assert (workflow_path.with_suffix(workflow_path.suffix + ".bak")).exists()

    data = read_yaml(workflow_path)
    steps = data["jobs"]["build"]["steps"]
    upload_step = steps[1]
    assert upload_step["with"]["retention-days"] == 7
    assert upload_step["with"]["name"] == "coverage.xml"
    download_step = steps[2]
    assert download_step["with"]["name"] == "artifacts"
    helper_step = steps[3]
    assert helper_step["name"] == HELPER_STEP_NAME
    assert helper_step["if"] == "always()"
    assert helper_step["run"] == "ls -R ./artifacts || true"


def test_multi_file_upgrade(tmp_path: Path) -> None:
    write_workflow(
        tmp_path,
        "upload.yml",
        """
name: Upload
jobs:
  upload_job:
    steps:
      - uses: actions/upload-artifact@v3
        with:
          path: dist/output.tar
""",
    )
    write_workflow(
        tmp_path,
        "download.yml",
        """
name: Download
jobs:
  download_job:
    steps:
      - uses: actions/download-artifact@v3
        with:
          path: ./downloads
""",
    )

    result = run_cli(tmp_path, "--write")
    assert result.returncode == 0

    upload_data = read_yaml(tmp_path / ".github" / "workflows" / "upload.yml")
    download_data = read_yaml(tmp_path / ".github" / "workflows" / "download.yml")

    upload_step = upload_data["jobs"]["upload_job"]["steps"][0]
    assert upload_step["uses"] == "actions/upload-artifact@v4"
    assert upload_step["with"]["name"] == "output.tar"

    download_steps = download_data["jobs"]["download_job"]["steps"]
    assert download_steps[0]["uses"] == "actions/download-artifact@v4"
    assert download_steps[0]["with"]["name"] == "downloads"
    assert any(step.get("name") == HELPER_STEP_NAME for step in download_steps)


def test_inject_name_from_multiple_paths(tmp_path: Path) -> None:
    write_workflow(
        tmp_path,
        "multi.yml",
        """
name: Multiple
jobs:
  multi_job:
    steps:
      - uses: actions/upload-artifact@v3
        with:
          path:
            - build/dist/app.whl
            - build/dist/app.tar.gz
""",
    )

    result = run_cli(tmp_path, "--write")
    assert result.returncode == 0

    data = read_yaml(tmp_path / ".github" / "workflows" / "multi.yml")
    step = data["jobs"]["multi_job"]["steps"][0]
    assert step["with"]["name"] == "app.whl-app.tar.gz"


def test_dry_run_diff_contains_changes(tmp_path: Path) -> None:
    write_workflow(
        tmp_path,
        "diff.yml",
        """
name: Diff
jobs:
  diff_job:
    steps:
      - uses: actions/download-artifact@v3
        with:
          path: ./artifact_dir
""",
    )

    result = run_cli(tmp_path, "--dry-run")
    assert result.returncode == 0
    assert "actions/download-artifact@v3" in result.stdout
    assert "actions/download-artifact@v4" in result.stdout
    assert COMMENT_TEXT in result.stdout


def test_idempotent_second_run(tmp_path: Path) -> None:
    write_workflow(
        tmp_path,
        "idempotent.yml",
        """
name: Idempotent
jobs:
  job:
    steps:
      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          path: reports/report.xml
""",
    )

    first = run_cli(tmp_path, "--write")
    assert first.returncode == 0

    second = run_cli(tmp_path, "--dry-run")
    assert second.returncode == 0
    assert "no changes needed" in second.stdout
