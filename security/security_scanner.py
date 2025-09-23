# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List


def run_pip_audit() -> Dict[str, Any]:  # pragma: no cover - external command
    try:
        out = subprocess.check_output(["pip", "audit", "-f", "json"], text=True)
        return json.loads(out)
    except Exception as ex:
        return {"error": str(ex)}


def run_bandit() -> Dict[str, Any]:  # pragma: no cover - external command
    try:
        out = subprocess.check_output(["bandit", "-r", "src", "-f", "json"], text=True)
        return json.loads(out)
    except Exception as ex:
        return {"error": str(ex)}

