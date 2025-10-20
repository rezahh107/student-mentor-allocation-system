from __future__ import annotations

import json
from pathlib import Path


def test_devcontainer_post_create_installs_dev_extras():
    config = json.loads(Path(".devcontainer/devcontainer.json").read_text(encoding="utf-8"))
    command = config.get("postCreateCommand", "")
    assert "pip install -e .[dev]" in command, "دستور postCreate باید نصب dev را اجرا کند (AGENTS.md::8 Testing & CI Gates)."
    fallback_index = command.find("|| pip install -e .")
    primary_index = command.find("pip install -e .[dev]")
    assert primary_index != -1 and fallback_index > primary_index, "ابتدا باید نصب dev انجام شود و سپس مسیر پشتیبان فعال باشد."
