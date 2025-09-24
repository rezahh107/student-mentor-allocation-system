# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from src.phase2_counter_service.config import load_from_env


def test_load_from_env_valid(monkeypatch):
    monkeypatch.setenv("DB_URL", "sqlite:///tmp.db")
    monkeypatch.setenv("PII_HASH_SALT", "salt")
    monkeypatch.setenv("METRICS_PORT", "9200")
    monkeypatch.setenv("ENV", "prod")
    config = load_from_env()
    assert config.db_url == "sqlite:///tmp.db"
    assert config.metrics_port == 9200
    assert config.env == "prod"


def test_load_from_env_invalid_port(monkeypatch):
    monkeypatch.setenv("METRICS_PORT", "-10")
    with pytest.raises(ValueError):
        load_from_env()


def test_load_from_env_invalid_env(monkeypatch):
    monkeypatch.setenv("ENV", "qa")
    with pytest.raises(ValueError):
        load_from_env()
