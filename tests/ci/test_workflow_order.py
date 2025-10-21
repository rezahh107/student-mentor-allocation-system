from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from freezegun import freeze_time
from ruamel.yaml import YAML

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load_yaml(path: Path) -> Dict[str, Any]:
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.load(handle) or {}


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
@freeze_time("2024-05-01T08:15:00+03:30")
def test_install_and_preflight_precede_pytest() -> None:
    workflow_paths = sorted(WORKFLOWS_DIR.glob("*.yml"))
    assert workflow_paths, "هیچ workflowی یافت نشد."
    for workflow_path in workflow_paths:
        document = _load_yaml(workflow_path)
        jobs: Dict[str, Any] = document.get("jobs", {})
        for job_name, job in jobs.items():
            steps: List[Dict[str, Any]] = job.get("steps", [])
            install_index = None
            preflight_index = None
            middleware_guard_seen = False
            install_env_verified = False
            pytest_indices: List[int] = []
            for idx, step in enumerate(steps):
                run_command = step.get("run", "")
                name = step.get("name", f"step-{idx}")
                step_env = step.get("env", {})
                if "Install (constraints-aware, retry)" in name:
                    install_index = idx
                    install_env_verified = step_env.get("PIP_REQUIRE_HASHES") == ""
                if "scripts.ci.ensure_ci_ready" in run_command:
                    preflight_index = idx
                if "python -m pytest" in run_command:
                    pytest_indices.append(idx)
                    assert install_index is not None, (
                        f"Install step missing before pytest in {workflow_path}:{job_name}:{name}"
                    )
                    assert install_index < idx, (
                        f"Install step must precede pytest in {workflow_path}:{job_name}:{name}"
                    )
                    assert preflight_index is not None and preflight_index < idx, (
                        f"Preflight guard missing before pytest in {workflow_path}:{job_name}:{name}"
                    )
                    if "tests/api/test_middleware_order.py" in run_command:
                        middleware_guard_seen = True
            debug_context = {
                "workflow": str(workflow_path),
                "job": job_name,
                "pytest_indices": pytest_indices,
                "install_index": install_index,
                "preflight_index": preflight_index,
                "install_env_verified": install_env_verified,
            }
            assert install_env_verified, f"PIP_REQUIRE_HASHES unset check failed: {debug_context}"
            assert middleware_guard_seen, (
                "Middleware guard missing; expected python -m pytest tests/api/test_middleware_order.py "
                f"before suite → context={debug_context}"
            )


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
@freeze_time("2024-05-01T08:15:00+03:30")
def test_pytest_disable_autoload_env_present() -> None:
    workflow_paths = sorted(WORKFLOWS_DIR.glob("*.yml"))
    for workflow_path in workflow_paths:
        document = _load_yaml(workflow_path)
        env = document.get("env", {})
        assert env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1", (
            f"PYTEST_DISABLE_PLUGIN_AUTOLOAD missing in {workflow_path}"
        )
