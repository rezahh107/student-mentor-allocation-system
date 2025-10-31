
from __future__ import annotations
import json, re, uuid
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
    """Minimal counter container for local Prometheus output."""

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


def serve_metrics_guarded(metrics: DoctorMetrics, headers: dict[str, str] | None) -> tuple[int, dict[str, str], bytes]:
    """Render metrics without enforcing a bearer token."""

    correlation_id = uuid.uuid4().hex
    payload = "\n".join(
        (
            "# HELP reqs_doctor_plan_total Number of plan operations",
            "# TYPE reqs_doctor_plan_total counter",
            f"reqs_doctor_plan_total {metrics.plan}",
            "# HELP reqs_doctor_fix_total Number of fix operations",
            "# TYPE reqs_doctor_fix_total counter",
            f"reqs_doctor_fix_total {metrics.fix}",
        )
    ).encode("utf-8")
    response_headers = {
        "Content-Type": "text/plain; version=0.0.4",
        "X-Correlation-ID": correlation_id,
    }
    return 200, response_headers, payload


__all__ = ["DoctorMetrics", "JsonLogger", "serve_metrics_guarded"]
