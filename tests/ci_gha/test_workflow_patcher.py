from __future__ import annotations

import io
import time
import textwrap
from pathlib import Path

import pytest

from tools import gha_workflow_patcher


def _write_workflow(
    path: Path,
    *,
    windows: bool = False,
    extra_matrix: str = "",
    with_env: bool = False,
) -> None:
    newline = "\r\n" if windows else "\n"
    lines = [
        "name: Targeted tests",
        "on:",
        "  push:",
        "    branches: [main]",
        "jobs:",
        "  targeted:",
        "    runs-on: ubuntu-latest",
    ]
    matrix_block = textwrap.dedent(extra_matrix).strip("\n") if extra_matrix else ""
    if matrix_block:
        for raw in matrix_block.splitlines():
            lines.append("    " + raw)
    lines.append("    steps:")
    step_lines = [
        "      - name: Checkout",
        "        uses: actions/checkout@v4",
        "      - name: Execute tests",
    ]
    if with_env:
        step_lines.extend(
            [
                "        env:",
                "          CUSTOM_ENV: one",
            ]
        )
    step_lines.extend(
        [
            "        run: |",
            "          export TARGET=ci",
            "          pytest -q -k \"excel or admin\"",
        ]
    )
    lines.extend(step_lines)
    content = newline.join(lines)
    path.write_text(content, encoding="utf-8")


def _prepare_repo(root: Path, **kwargs) -> Path:
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = workflow_dir / "ci.yml"
    _write_workflow(workflow_file, **kwargs)
    runner = root / "tools"
    runner.mkdir(parents=True, exist_ok=True)
    (runner / "ci_pytest_runner.py").write_text("print('ok')\n", encoding="utf-8")
    return workflow_file


def _prepare_repo_with_content(root: Path, content: str) -> Path:
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = workflow_dir / "ci.yml"
    workflow_file.write_text(textwrap.dedent(content).strip("\n") + "\n", encoding="utf-8")
    runner = root / "tools"
    runner.mkdir(parents=True, exist_ok=True)
    (runner / "ci_pytest_runner.py").write_text("print('ok')\n", encoding="utf-8")
    return workflow_file


def test_patcher_updates_workflow_with_matrix(clean_state, retry_call, tmp_path, capsys):
    repo_root = tmp_path / "repo-a"
    repo_root.mkdir()
    workflow_file = _prepare_repo(repo_root)

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root)]))
    assert rc == 0, f"پچر باید موفق باشد؛ زمینه: {workflow_file}"

    stdout = capsys.readouterr().out
    assert "mode: [stub, redis]" in stdout, f"diff باید ماتریس را نمایش دهد: {stdout}"

    updated = workflow_file.read_text(encoding="utf-8")
    assert "Install dependencies (with extras)" in updated, "گام نصب افزوده نشد"
    assert "Select mode env" in updated, "گام انتخاب env افزوده نشد"
    assert RUNNER_COMMAND in updated, "دستور نهایی جایگزین نشد"
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in updated, "env باید تنظیم شود"


def test_patcher_idempotent(clean_state, retry_call, tmp_path, capsys):
    repo_root = tmp_path / "repo-b"
    repo_root.mkdir()
    workflow_file = _prepare_repo(repo_root)

    rc_first = retry_call(lambda: gha_workflow_patcher.run([str(repo_root)]))
    assert rc_first == 0, f"اجرای اول شکست خورد؛ فایل: {workflow_file}"
    capsys.readouterr()

    rc_second = retry_call(lambda: gha_workflow_patcher.run([str(repo_root)]))
    assert rc_second == 0, "اجرای دوم باید موفق باشد"
    output = capsys.readouterr().out
    assert "PATCH_IDEMPOTENT" in output, f"انتظار پیام بی‌تغییری داشتیم: {output}"


def test_text_fallback_handles_windows_and_multiline(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-c"
    repo_root.mkdir()
    workflow_file = _prepare_repo(repo_root, windows=True)

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "اجرای اجباری متنی باید موفق شود"

    updated = workflow_file.read_text(encoding="utf-8")
    assert b"\r\n" in workflow_file.read_bytes(), "خط جدید ویندوز باید حفظ شود"
    assert RUNNER_COMMAND in updated, "دستور انتظار می‌رفت در فایل باشد"
    assert updated.count("Select mode env") == 1, "گام env نباید تکراری شود"


def test_merges_existing_matrix_without_duplication(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-d"
    repo_root.mkdir()
    extra_matrix = textwrap.dedent(
        """
            strategy:
              matrix:
                python-version: ["3.11"]
                include:
                  - python-version: "3.11"
                    flag: true
        """
    )
    workflow_file = _prepare_repo(repo_root, extra_matrix=extra_matrix)

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "پچ با ماتریس اولیه باید موفق شود"

    updated = workflow_file.read_text(encoding="utf-8")
    assert "mode: [stub, redis]" in updated, "محور mode باید اضافه شود"
    assert updated.count("mode: [stub, redis]") == 1, "mode نباید تکراری شود"
    assert "include:" in updated, "بخش include باید حفظ شود"


def test_conflicting_mode_axis_raises(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-e"
    repo_root.mkdir()
    extra_matrix = textwrap.dedent(
        """
            strategy:
              matrix:
                mode: [foo]
        """
    )
    workflow_file = _prepare_repo(repo_root, extra_matrix=extra_matrix)

    with pytest.raises(gha_workflow_patcher.PatchError) as exc:
        retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))

    message = str(exc.value)
    assert "PATCH_CONFLICT_MATRIX" in message, f"باید پیام تضاد برگردد: {message}"


def test_existing_mode_multiline_is_respected(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-f"
    repo_root.mkdir()
    extra_matrix = textwrap.dedent(
        """
            strategy:
              matrix:
                mode:
                  - stub
                  - redis
        """
    )
    workflow_file = _prepare_repo(repo_root, extra_matrix=extra_matrix)

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "وجود محور mode سازگار باید بدون تغییر خاتمه یابد"

    output = workflow_file.read_text(encoding="utf-8")
    assert output.count("Install dependencies (with extras)") == 1, "steps نباید تکرار شوند"


def test_existing_env_block_preserved(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-g"
    repo_root.mkdir()
    workflow_file = _prepare_repo(repo_root, with_env=True)

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "وجود env نباید مانع patch شود"

    content = workflow_file.read_text(encoding="utf-8")
    assert "CUSTOM_ENV: one" in content, "env موجود باید باقی بماند"
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in content, "متغیر افزوده باید حاضر باشد"
    assert content.count("env:") == 1, "نباید بلاک env تکرار شود"


def test_multiple_pytest_steps_rewritten(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-multi"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        """
        name: Multi runner
        on:
          push:
            branches: [main]
        jobs:
          matrixed:
            runs-on: ubuntu-latest
            steps:
              - name: First setup
                run: echo ok
              - name: Execute first suite
                run: pytest -q first
              - name: Execute second suite
                run: |
                  echo start
                  pytest -q second
        """,
    )

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "پچ باید تمام مراحل pytest را پوشش دهد"

    updated = workflow_file.read_text(encoding="utf-8")
    assert updated.count(RUNNER_COMMAND) == 2, "هر دو مرحله باید با رانر جایگزین شوند"
    assert "pytest -q" not in updated, "نباید فرمان pytest خام باقی بماند"
    assert updated.count("Install dependencies (with extras)") == 1, "گام نصب باید یکتا باشد"
    assert updated.count("Select mode env") == 1, "گام انتخاب env باید یکبار درج شود"
    assert "Execute first suite (via CI runner)" in updated, "نام مرحله اول باید suffix بگیرد"
    assert "Execute second suite (via CI runner)" in updated, "نام مرحله دوم باید suffix بگیرد"


def test_anchor_and_comment_preserved(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-anchor"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        """
        name: Anchor sample
        on: [push]
        jobs:
          anchored:
            runs-on: ubuntu-latest
            steps:
              - name: Execute suite &pytest_anchor  # critical
                run: pytest -q -k critical
        """,
    )

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "پچ مراحل دارای anchor باید موفق باشد"

    line = next(
        line
        for line in workflow_file.read_text(encoding="utf-8").splitlines()
        if "pytest_anchor" in line
    )
    assert (
        "Execute suite (via CI runner) &pytest_anchor  # critical" in line
    ), f"anchor و توضیح باید حفظ شوند: {line}"


def test_anchor_alias_expanded_steps(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-anchor-alias"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        """
        name: Anchor alias
        on: [push]
        jobs:
          anchored:
            runs-on: ubuntu-latest
            steps:
              - &pytest_template
                name: Anchored suite
                run: |
                  echo start
                  pytest -q anchor-main
              - <<: *pytest_template
                name: Anchored suite copy  # trailing comment
        """,
    )

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "مرحله‌های دارای alias باید بازنویسی شوند"

    content = workflow_file.read_text(encoding="utf-8")
    assert RUNNER_COMMAND in content, "فرمان رانر باید در خروجی وجود داشته باشد"
    assert "pytest -q" not in content, "دستور pytest نباید باقی بماند"
    assert "&pytest_template" in content, "anchor باید حفظ شود"
    assert "Anchored suite copy  # trailing comment" in content, "توضیح باید حفظ شود"


def test_folded_run_block_detected(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-folded"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        """
        name: Folded block
        on: [push]
        jobs:
          folded:
            runs-on: ubuntu-latest
            steps:
              - name: Folded pytest
                run: >
                  set -e
                  pytest -q folded
        """,
    )

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "بلاک run نوع folded باید شناسایی شود"

    content = workflow_file.read_text(encoding="utf-8")
    assert RUNNER_COMMAND in content, "فرمان رانر باید جایگزین شود"
    assert "run: >" not in content, "بلاک folded باید به pipe تبدیل شود"


def test_large_workflow_patched_under_budget(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-large"
    repo_root.mkdir()
    steps = [
        "name: Large workflow",
        "on:",
        "  push:",
        "jobs:",
        "  big:",
        "    runs-on: ubuntu-latest",
        "    steps:",
    ]
    for idx in range(1700):
        steps.append(f"      - name: Step {idx}")
        steps.append("        run: |")
        if idx == 1699:
            steps.append("          pytest -q massive")
        else:
            steps.append("          echo noop")
    workflow_file = _prepare_repo_with_content(repo_root, "\n".join(steps))

    start = time.monotonic()
    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    end = time.monotonic()
    assert rc == 0, "پچ روی فایل بزرگ باید موفق باشد"
    assert (end - start) <= 0.3, f"اجرای پچ باید زیر 0.3 ثانیه بماند؛ مقدار {end - start}"
    assert RUNNER_COMMAND in workflow_file.read_text(encoding="utf-8"), "رانر باید جایگزین شود"


def test_text_patch_matches_golden_snapshot(clean_state, retry_call, tmp_path):
    repo_root = tmp_path / "repo-golden"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        (Path(__file__).parent / "data" / "sample_workflow_before.yml").read_text(encoding="utf-8"),
    )

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc == 0, "پچ نمونهٔ طلایی باید موفق شود"

    expected = (Path(__file__).parent / "golden" / "sample_workflow_after.yml").read_text(
        encoding="utf-8"
    )
    actual = workflow_file.read_text(encoding="utf-8")
    assert actual == expected, "خروجی پچ باید با فایل طلایی یکسان باشد"


def test_duplicate_job_names_tracked_by_offsets(clean_state, retry_call, tmp_path, capsys):
    repo_root = tmp_path / "repo-duplicate"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        """
        name: Duplicate jobs
        on: [push]
        jobs:
          alpha:
            name: مشترک
            runs-on: ubuntu-latest
            steps:
              - name: Execute alpha tests
                run: pytest -q alpha-one
              - name: Execute alpha extra
                run: pytest -q alpha-two
          beta:
            name: مشترک
            runs-on: ubuntu-latest
            steps:
              - name: Execute beta tests
                run: pytest -q beta-one
        """,
    )

    rc_first = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc_first == 0, "اجرای اول باید موفق شود"

    content = workflow_file.read_text(encoding="utf-8")
    assert content.count("mode: [stub, redis]") == 2, "محور mode باید برای هر job فقط یکبار اضافه شود"
    assert content.count("Install dependencies (with extras)") == 2, "گام نصب باید در هر job درج شود"
    assert content.count("Select mode env") == 2, "گام انتخاب env باید تکرار نشود"
    assert "pytest -q" not in content, "فرمان pytest نباید باقی بماند"

    capsys.readouterr()
    rc_second = retry_call(lambda: gha_workflow_patcher.run([str(repo_root), "--force-text"]))
    assert rc_second == 0, "اجرای دوم باید بدون خطا خاتمه یابد"
    no_change_output = capsys.readouterr().out
    assert "PATCH_IDEMPOTENT" in no_change_output, "اجرای دوم باید بدون تغییر باشد"


def test_ruamel_reorders_support_steps(clean_state, retry_call, tmp_path, capsys):
    yaml_mod = pytest.importorskip("ruamel.yaml")
    repo_root = tmp_path / "repo-ruamel"
    repo_root.mkdir()
    workflow_file = _prepare_repo_with_content(
        repo_root,
        """
        name: Ruamel reorder
        on: [push]
        jobs:
          reorder:
            runs-on: ubuntu-latest
            strategy:
              matrix:
                python-version: ["3.11"]
            steps:
              - name: Run targeted pytest suite
                if: success()
                env:
                  SAMPLE: yes
                run: pytest -q reorder-suite
              - name: Install dependencies (with extras)
                continue-on-error: true
                run: |
                  python -m pip install --upgrade pip
                  pip install -e ".[fastapi,redis,dev]" || true
                  pip install fastapi redis pytest-asyncio uvicorn httpx pytest prometheus-client
              - name: Select mode env
                timeout-minutes: 5
                run: |
                  if [ "${{ matrix.mode }}" = "stub" ]; then
                    echo "TEST_REDIS_STUB=1" >> $GITHUB_ENV
                  else
                    echo "PYTEST_REDIS=1" >> $GITHUB_ENV
                  fi
        """,
    )

    rc = retry_call(lambda: gha_workflow_patcher.run([str(repo_root)]))
    assert rc == 0, "اجرای مسیر ruamel باید موفق شود"

    stdout = capsys.readouterr().out
    assert "بازچینش=true" in stdout, f"انتظار پیام بازچینش داشتیم: {stdout}"

    actual_text = workflow_file.read_text(encoding="utf-8")
    golden_path = Path(__file__).parent / "golden" / "ruamel_reorder.yml"
    expected_text = golden_path.read_text(encoding="utf-8")
    YAML = yaml_mod.YAML
    yaml_loader = YAML(typ="rt")
    yaml_loader.preserve_quotes = True
    expected_data = yaml_loader.load(expected_text)
    buffer = io.StringIO()
    yaml_loader.dump(expected_data, buffer)
    normalized_expected = buffer.getvalue()
    assert actual_text == normalized_expected, "خروجی ruamel باید با فایل طلایی یکسان باشد"


# ثابت از ماژول برای ارجاع در تست‌ها
RUNNER_COMMAND = gha_workflow_patcher.RUNNER_COMMAND
