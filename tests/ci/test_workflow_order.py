from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML


WORKFLOWS = [
    Path(".github/workflows/test.yml"),
    Path(".github/workflows/linux-tests.yml"),
    Path(".github/workflows/windows-smoke.yml"),
]


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
@pytest.mark.evidence("Tailored v2.4 §2 pip-tools")
def test_ci_workflows_enforce_install_preflight_order() -> None:
    yaml = YAML(typ="safe")
    for workflow_path in WORKFLOWS:
        data = yaml.load(workflow_path.read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            steps = [step for step in job.get("steps", []) if "name" in step]
            names = [step["name"] for step in steps]
            assert "Install (constraints-aware, retry)" in names, workflow_path
            assert "Preflight (pytest ready)" in names, workflow_path
            install_index = names.index("Install (constraints-aware, retry)")
            preflight_index = names.index("Preflight (pytest ready)")
            assert install_index < preflight_index, workflow_path
            tests_indices = [idx for idx, name in enumerate(names) if name.startswith("Run tests") or "Smoke Tests" in name]
            assert tests_indices and preflight_index < min(tests_indices), workflow_path
            install_step = steps[install_index]
            run_script = install_step.get("run", "")
            assert "python -m scripts.ci.bootstrap_guard" in run_script
            assert "python -m scripts.deps.ensure_lock --root . install" in run_script
            env = install_step.get("env", {})
            assert env.get("PIP_REQUIRE_HASHES") == "" or env.get("PIP_REQUIRE_HASHES") == "''"
