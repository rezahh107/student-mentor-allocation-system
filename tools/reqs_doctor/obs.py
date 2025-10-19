
from __future__ import annotations
import json, os, re, uuid
from typing import Any, Dict

TOKEN_PAT = re.compile(r"(?i)(bearer\s+[a-z0-9\.\-_]+|x-metrics-token\s*=\s*[A-Za-z0-9\.\-_]+)")
URL_PAT = re.compile(r"https?://[^\s\"']+")

class JsonLogger:
    @staticmethod
    def redact(text: str) -> str:
        text = TOKEN_PAT.sub("**REDACTED**", text)
        text = URL_PAT.sub("**URL**", text)
        return text
    @staticmethod
    def dumps(payload: Dict[str, Any]) -> str:
        # redacts on the JSON string level
        s = json.dumps(payload, ensure_ascii=False)
        return JsonLogger.redact(s)

class DoctorMetrics:
    # Minimal stub (no prometheus dependency)
    def __init__(self) -> None:
        self.plan = 0
        self.fix = 0
    @classmethod
    def fresh(cls) -> "DoctorMetrics":
        return cls()
    def observe_plan(self) -> None:
        self.plan += 1
    def observe_fix(self) -> None:
        self.fix += 1
