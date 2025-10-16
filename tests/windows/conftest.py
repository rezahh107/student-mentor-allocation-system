from __future__ import annotations

import os
import shutil

import pytest


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    config_root = tmp_path / "appdata"
    monkeypatch.setenv("STUDENT_MENTOR_APP_CONFIG_DIR", str(config_root))
    monkeypatch.setenv("FAKE_WEBVIEW", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    yield
    if config_root.exists():
        shutil.rmtree(config_root, ignore_errors=True)
