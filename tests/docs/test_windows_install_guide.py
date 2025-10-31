from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from pydantic import BaseModel

from sma.phase6_import_to_sabt.app.config import AppConfig

GUIDE_PATH = Path("docs/windows-install.md")
ENV_EXAMPLE_PATH = Path(".env.example.win")

windows_only = pytest.mark.windows_only


def _gather_settings_keys() -> set[str]:
    env_prefix = AppConfig.model_config.get("env_prefix", "")
    keys: set[str] = set()

    def walk(model: type[BaseModel], parts: list[str]) -> None:
        for name, field in model.model_fields.items():
            alias = field.alias or name
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                walk(annotation, parts + [alias])
                continue
            segment = "__".join(part.upper() for part in (parts + [alias]))
            keys.add(f"{env_prefix}{segment}")

    walk(AppConfig, [])
    return keys


@pytest.mark.parametrize(
    "expected_heading",
    [
        "## Native virtual environment (Recommended)",
        "## WSL2 path",
        "## Docker Desktop path",
        "## Troubleshooting",
        "## TL;DR (Recommended path)",
    ],
)
def test_windows_guide_sections(expected_heading: str) -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert expected_heading in content, f"heading missing: {expected_heading}"


def _extract_tldr_commands() -> list[str]:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    marker = "## TL;DR (Recommended path)"
    assert marker in content, "TL;DR heading missing"
    section = content.split(marker, maxsplit=1)[1]
    start = section.index("```powershell")
    end = section.index("```", start + 1)
    block = section[start:end].splitlines()[1:]
    return [line.strip() for line in block if line.strip()]


def test_tldr_commands_consistent() -> None:
    commands = _extract_tldr_commands()
    expected_order = [
        "cd E:",
        "git clone",
        "cd student-mentor-allocation-system",
        "pwsh -NoLogo -File scripts/win/00-diagnose.ps1",
        "pwsh -NoLogo -File scripts/win/10-venv-install.ps1",
        "pwsh -NoLogo -File scripts/win/20-create-env.ps1",
        "pwsh -NoLogo -File scripts/win/30-services.ps1",
        "pwsh -NoLogo -File scripts/win/40-run.ps1",
        "pwsh -NoLogo -File scripts/win/50-smoke.ps1",
        "pwsh -NoLogo -File scripts/win/30-services.ps1 -Action Cleanup",
    ]
    assert len(commands) == len(expected_order), (
        f"expected {len(expected_order)} commands, got {len(commands)}"
    )
    for prefix, command in zip(expected_order, commands, strict=True):
        assert command.startswith(prefix), f"expected {prefix} but saw {command}"
    for command in commands[3:]:
        parts = shlex.split(command)
        script = next((part for part in parts if part.endswith('.ps1')), None)
        if script:
            script_path = Path(script.replace('scripts\\', 'scripts/'))
            assert script_path.exists(), f"script not found: {script_path}"


def test_env_example_matches_settings() -> None:
    env_lines = ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
    env_values: dict[str, str] = {}
    for raw in env_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        env_values[key] = value

    required_keys = _gather_settings_keys()
    extras = {
        "METRICS_ENDPOINT_ENABLED",
        "IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS",
        "TOKENS",
        "DOWNLOAD_SIGNING_KEYS",
        "EXPORT_STORAGE_DIR",
    }
    actual_keys = set(env_values)
    expected_keys = required_keys | extras
    missing = expected_keys - actual_keys
    unexpected = actual_keys - expected_keys
    assert not missing, f"env example missing keys: {sorted(missing)}"
    assert not unexpected, f"env example has unexpected keys: {sorted(unexpected)}"

    redis_dsn = env_values.get("IMPORT_TO_SABT_REDIS__DSN", "")
    db_dsn = env_values.get("IMPORT_TO_SABT_DATABASE__DSN", "")
    assert redis_dsn.startswith("redis://"), "redis DSN sample should use redis://"
    assert "postgres" in db_dsn, "database DSN sample should target postgres"

    tokens_payload = json.loads(env_values["TOKENS"])
    assert isinstance(tokens_payload, list), "TOKENS must be a JSON list"
    assert tokens_payload, "TOKENS must contain at least one entry"
    keys_payload = json.loads(env_values["DOWNLOAD_SIGNING_KEYS"])
    assert isinstance(keys_payload, list), "DOWNLOAD_SIGNING_KEYS must be a JSON list"
    assert keys_payload, "DOWNLOAD_SIGNING_KEYS must contain signing keys"


def test_metrics_guard_documented() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "METRICS_ENDPOINT_ENABLED" in content
    assert "بدون نیاز به هدر" in content


@windows_only
def test_perf_guidance_present() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "p95" in content and "200ms" in content, "p95 latency guidance missing"
    assert "300MB" in content, "memory cap guidance missing"
