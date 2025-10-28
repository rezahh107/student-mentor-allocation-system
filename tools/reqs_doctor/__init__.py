"""Helpers for dependency and middleware documentation consistency."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_CLI_PATH = Path(__file__).resolve().parents[1] / "reqs_doctor.py"
_SPEC = importlib.util.spec_from_file_location("tools._reqs_doctor_cli", _CLI_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - defensive guard
    raise RuntimeError("reqs_doctor CLI module could not be loaded")
_CLI_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI_MODULE)

app = getattr(_CLI_MODULE, "app")
ensure_agents_md = getattr(_CLI_MODULE, "ensure_agents_md")

MIDDLEWARE_ORDER = ("RateLimit", "Idempotency", "Auth")
MIDDLEWARE_ORDER_DOC = " → ".join(MIDDLEWARE_ORDER)

__all__ = ["MIDDLEWARE_ORDER", "MIDDLEWARE_ORDER_DOC", "app", "ensure_agents_md"]
