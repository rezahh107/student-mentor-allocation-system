# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib

import pytest

from scripts import post_migration_checks


def test_post_migration_checks_pass():
    assert post_migration_checks.run_checks() == []


def test_post_migration_checks_fail_on_mapping(monkeypatch):
    monkeypatch.setattr("src.phase2_counter_service.validation.COUNTER_PREFIX", {0: "000", 1: "357"}, raising=False)
    importlib.reload(post_migration_checks)
    issues = post_migration_checks.run_checks()
    assert any("drifted" in issue for issue in issues)
    importlib.reload(post_migration_checks)
