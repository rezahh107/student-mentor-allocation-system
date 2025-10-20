#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
REQUIRED_TOKENS = {
    "Determinism",
    "Middleware",
    "Excel",
    "Testing & CI Gates",
}
EVIDENCE_TOKENS = [
    "AGENTS.md::1 Determinism",
    "AGENTS.md::3 Absolute Guardrails",
    "AGENTS.md::8 Testing & CI Gates",
]


def _emit(level: str, event: str, message: str, *, extra: dict[str, Any] | None = None, target=sys.stdout) -> None:
    correlation_id = os.environ.get("SMA_CORRELATION_ID", "verify-agents")
    payload = {
        "level": level,
        "event": event,
        "message": message,
        "correlation_id": correlation_id,
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=target)


if not AGENTS_PATH.exists():
    _emit(
        "error",
        "agents_missing",
        "پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.",
        target=sys.stderr,
    )
    sys.exit(1)

text = AGENTS_PATH.read_text(encoding="utf-8")
missing = sorted(token for token in REQUIRED_TOKENS if token not in text)
if missing:
    _emit(
        "error",
        "agents_keywords_missing",
        "خطا: واژگان ضروری در AGENTS.md یافت نشدند.",
        extra={"missing_tokens": missing},
        target=sys.stderr,
    )
    sys.exit(1)

_emit(
    "info",
    "agents_verified",
    "AGENTS.md تایید شد؛ واژگان کلیدی موجود است.",
    extra={"evidence": EVIDENCE_TOKENS, "required_tokens": sorted(REQUIRED_TOKENS)},
)
