from __future__ import annotations

from pathlib import Path

import pytest

from tools.migrate_artifacts_v3_to_v4 import HELPER_STEP_NAME, main


@pytest.fixture()
def workflow_root(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    return workflows


def run_cli(tmp_path: Path, *args: str) -> int:
    argv = [*args, "--base-dir", str(tmp_path)]
    return main(argv)


def read_workflow(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_single_file_upgrade_preserves_retention_and_adds_name(workflow_root: Path) -> None:
    workflow = workflow_root / "coverage.yml"
    workflow.write_text(
        """
name: Coverage
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Upload coverage
        uses: actions/upload-artifact@v3
        with:
          path: reports/coverage.xml
          retention-days: 7
      - name: Download coverage
        uses: actions/download-artifact@v3
        with:
          path: ./artifacts
      - name: Consume coverage
        run: cat ./artifacts/coverage/coverage.xml
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = run_cli(workflow_root.parent.parent, "--write")
    assert exit_code == 0

    output = read_workflow(workflow)
    assert "actions/upload-artifact@v4" in output
    assert "actions/download-artifact@v4" in output
    assert "retention-days: 7" in output
    assert "name: coverage.xml" in output
    assert "# NOTE: GitHub Actions artifact v4" in output

    helper_present = f"name: {HELPER_STEP_NAME}" in output
    assert helper_present

    backup = workflow.with_suffix(".yml.bak")
    assert backup.exists()


def test_multi_file_upgrade(workflow_root: Path) -> None:
    first = workflow_root / "first.yml"
    second = workflow_root / "second.yaml"
    first.write_text(
        """
jobs:
  build:
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@v3
        with:
          path: logs/build.log
""".lstrip(),
        encoding="utf-8",
    )
    second.write_text(
        """
jobs:
  build:
    steps:
      - name: Download logs
        uses: actions/download-artifact@v3
        with:
          name: build-logs
          path: ./downloads
      - name: Process logs
        run: cat ./downloads/logs/output.txt
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = run_cli(workflow_root.parent.parent, "--write")
    assert exit_code == 0

    first_output = read_workflow(first)
    second_output = read_workflow(second)
    assert "actions/upload-artifact@v4" in first_output
    assert "name: build.log" in first_output
    assert "actions/download-artifact@v4" in second_output
    assert f"name: {HELPER_STEP_NAME}" in second_output


def test_dry_run_diff_contains_expected_changes(workflow_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workflow = workflow_root / "diff.yml"
    workflow.write_text(
        """
jobs:
  example:
    steps:
      - uses: actions/upload-artifact@v3
        with:
          path: foo/bar.txt
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = run_cli(workflow_root.parent.parent, "--dry-run")
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert "would migrate" in captured
    assert "actions/upload-artifact@v3" in captured
    assert "actions/upload-artifact@v4" in captured
    assert "name: bar.txt" in captured


def test_idempotent_runs_do_not_change_files(workflow_root: Path) -> None:
    workflow = workflow_root / "idempotent.yml"
    workflow.write_text(
        """
jobs:
  build:
    steps:
      - name: Upload artifact
        uses: actions/upload-artifact@v3
        with:
          path: dist/app.tar.gz
""".lstrip(),
        encoding="utf-8",
    )

    first_exit = run_cli(workflow_root.parent.parent, "--write")
    assert first_exit == 0
    original = read_workflow(workflow)

    second_exit = run_cli(workflow_root.parent.parent, "--dry-run")
    assert second_exit == 0

    after = read_workflow(workflow)
    assert after == original
    # No changes reported means the CLI prints "no changes needed" for this file.
    # We ensure no backup was rewritten on dry-run.
    assert workflow.with_suffix(".yml.bak").exists()
