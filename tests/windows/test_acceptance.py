from __future__ import annotations

import hashlib
import os
import re
import string
from pathlib import Path

import pytest

from sma.phase6_import_to_sabt.app.config import AppConfig

pytestmark = pytest.mark.windows_only

MANDATORY_IMPORT_KEYS = {
    "IMPORT_TO_SABT_REDIS__DSN": "redis://127.0.0.1:6379/0",
    "IMPORT_TO_SABT_DATABASE__DSN": "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/student_mentor",
    "IMPORT_TO_SABT_AUTH__METRICS_TOKEN": "dev-metrics-token",
    "IMPORT_TO_SABT_AUTH__SERVICE_TOKEN": "dev-service-token",
    "IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS": "true",
}


@pytest.fixture
def clean_import_env():
    """Ensure IMPORT_TO_SABT_* variables do not leak between tests."""
    original = {k: os.environ[k] for k in os.environ if k.startswith("IMPORT_TO_SABT_")}
    for key in list(original):
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key in [name for name in os.environ if name.startswith("IMPORT_TO_SABT_")]:
            os.environ.pop(key, None)
        os.environ.update(original)


def normalize_env_file(env_path: Path, updates: dict[str, str]) -> list[str]:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    updated_keys: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, value = line.split("=", 1)
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(f"{key}={value}")
    for key, value in updates.items():
        if key not in updated_keys and all(not ln.startswith(f"{key}=") for ln in new_lines):
            new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return new_lines


def load_env(env_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key] = value
    return result


def random_namespace(source: str, prefix: str = "win") -> str:
    digest = hashlib.blake2s(source.encode("utf-8"), digest_size=5).hexdigest()
    suffix = "".join(ch for ch in digest if ch in string.ascii_lowercase + string.digits)[:6]
    return f"{prefix}-{suffix}" if suffix else f"{prefix}-{digest[:6]}"


def test_env_normalization_is_idempotent(tmp_path: Path, clean_import_env):
    env_path = tmp_path / ".env"
    env_path.write_text(Path(".env.example").read_text(encoding="utf-8"), encoding="utf-8")

    namespace = random_namespace(str(env_path))
    updates = MANDATORY_IMPORT_KEYS | {"IMPORT_TO_SABT_AUTH__METRICS_TOKEN": f"{namespace}-token"}

    first_pass = normalize_env_file(env_path, updates)
    second_pass = normalize_env_file(env_path, updates)
    assert first_pass == second_pass, (
        "Normalization changed on second pass",
        {
            "namespace": namespace,
            "first_len": len(first_pass),
            "second_len": len(second_pass),
        },
    )

    merged = load_env(env_path)
    pattern = re.compile(r"^IMPORT_TO_SABT_[A-Z0-9]+__[A-Z0-9_]+$")
    bad_keys = {
        k: merged[k]
        for k in merged
        if k.startswith("IMPORT_TO_SABT_") and "__" in k and not pattern.match(k)
    }
    assert not bad_keys, f"Unexpected key format: {bad_keys}"


def test_app_config_instantiates_with_normalized_env(tmp_path: Path, clean_import_env, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(Path(".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    normalize_env_file(env_path, MANDATORY_IMPORT_KEYS)

    env_values = load_env(env_path)
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    cfg = AppConfig()
    assert cfg is not None, f"AppConfig returned None. Context: {env_values.keys()}"

    expected_token = env_values["IMPORT_TO_SABT_AUTH__METRICS_TOKEN"]
    assert expected_token, "Metrics token missing after normalization"
