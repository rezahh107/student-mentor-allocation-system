from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest


@pytest.mark.ci
def test_repo_default_addopts_no_warnings() -> None:
    """AGENTS.md::Testing & CI Gates — ensure CI runs full pytest suite without warning skips."""

    config_path = Path(__file__).resolve().parents[2] / "pytest.ini"
    parser = ConfigParser()
    with config_path.open("r", encoding="utf-8") as handle:
        parser.read_file(handle)

    assert parser.has_section("pytest"), "pytest.ini missing [pytest] section"
    addopts = parser.get("pytest", "addopts", fallback="")
    required_flags = [
        "--strict-markers",
        "--strict-config",
        "-ra",
        "--durations=20",
        "--tb=short",
        "--showlocals",
        "-W",
        "-n=auto",
        "--dist=loadscope",
        "-p",
        "pytest_asyncio",
        "-p",
        "xdist.plugin",
        "-p",
        "pytest_timeout",
    ]
    for flag in required_flags:
        assert flag in addopts, f"Expected {flag} in pytest addopts"

    tokens = addopts.split()
    assert "-k" not in tokens, "pytest.ini must not hardcode -k filters"
    assert "-m" not in tokens, "pytest.ini must not hardcode -m markers"

    filterwarnings = parser.get("pytest", "filterwarnings", fallback="").splitlines()
    normalized = [line.strip() for line in filterwarnings if line.strip()]
    assert "error" in normalized, "filterwarnings must escalate unexpected warnings"

    markers = parser.get("pytest", "markers", fallback="").splitlines()
    normalized_markers = [line.strip().split(":")[0] for line in markers if line.strip()]
    for marker in ("performance", "stress", "ui", "metrics", "middleware"):
        assert marker in normalized_markers, f"Missing required marker: {marker}"
