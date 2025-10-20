# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import importlib

counter_init = importlib.import_module("sma.phase2_counter_service")
from sma.phase2_counter_service.config import ServiceConfig


def test_assign_counter_bootstrap(monkeypatch):
    counter_init._bootstrap.cache_clear()
    fake_service = SimpleNamespace(assign_counter=lambda *args: "253730001")
    fake_config = ServiceConfig(db_url="sqlite://", pii_hash_salt="salt", metrics_port=9100, env="dev")
    monkeypatch.setattr(counter_init, "load_from_env", lambda: fake_config)
    monkeypatch.setattr(counter_init, "make_engine", lambda dsn: "engine")
    monkeypatch.setattr(counter_init, "make_session_factory", lambda engine: "factory")
    monkeypatch.setattr(counter_init, "SqlAlchemyCounterRepository", lambda factory: "repo")
    monkeypatch.setattr(counter_init, "build_logger", lambda name="counter-service": SimpleNamespace(info=lambda *a, **k: None))
    monkeypatch.setattr(counter_init, "make_hash_fn", lambda salt: (lambda nid: "hash"))
    monkeypatch.setattr(counter_init, "CounterAssignmentService", lambda repo, meters, logger, hash_fn: fake_service)

    result = counter_init.assign_counter("1234567890", 0, "25")
    assert result == "253730001"
    assert counter_init.get_config() is fake_config
    counter_init._bootstrap.cache_clear()
