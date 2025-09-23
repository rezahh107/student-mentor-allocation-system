# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


def test_performance_baseline_regression():
    data = json.loads(Path(__file__).with_name("baseline_metrics.json").read_text(encoding="utf-8"))
    assert data["baseline"]["alloc_10k_sec"] <= data["target"]["alloc_10k_sec"]
    assert data["baseline"]["qps"] >= data["target"]["qps_min"]

