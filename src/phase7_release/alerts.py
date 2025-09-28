"""Prometheus alert rule and Alertmanager generation helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from .atomic import atomic_write

_BUDGETS = {
    "healthz": 0.2,
    "readyz": 0.2,
    "export_p95": 15.0,
    "export_memory_mb": 150,
}


class AlertCatalog:
    """Materialize alerting configuration with deterministic ordering."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def write_slo_rules(self, path: Path) -> None:
        groups = [
            {
                "name": "importtosabt-slo",
                "interval": "30s",
                "rules": [
                    _latency_alert(
                        name="ImportToSabtHealthzLatencyBudget",
                        path="/healthz",
                        threshold=_BUDGETS["healthz"],
                        summary="پاسخ سلامت کند است",
                        slo="healthz",
                    ),
                    _latency_alert(
                        name="ImportToSabtReadyzLatencyBudget",
                        path="/readyz",
                        threshold=_BUDGETS["readyz"],
                        summary="پاسخ آمادگی کند است",
                        slo="readyz",
                    ),
                    {
                        "alert": "ImportToSabtExportLatencyBudget",
                        "expr": (
                            "histogram_quantile(0.95, "
                            "sum(rate(importtosabt_export_seconds_bucket{profile=\"SABT_V1\"}[10m])) by (le)) "
                            f"> {_BUDGETS['export_p95']}"
                        ),
                        "for": "10m",
                        "labels": {
                            "severity": "critical",
                            "service": "import_to_sabt",
                            "budget": "export_p95_lt_15s",
                            "slo": "export_latency",
                        },
                        "annotations": {
                            "summary": "تاخیر زیاد در خروجی",
                            "description": "زمان اجرای صادرکننده از بودجه عبور کرده است",
                        },
                    },
                    {
                        "alert": "ImportToSabtExportMemoryBudget",
                        "expr": (
                            "max_over_time(process_resident_memory_bytes{service=\"import_to_sabt\"}[5m]) "
                            f"> {_BUDGETS['export_memory_mb']} * 1024 * 1024"
                        ),
                        "for": "5m",
                        "labels": {
                            "severity": "warning",
                            "service": "import_to_sabt",
                            "budget": "export_mem_lt_150mb",
                            "slo": "export_memory",
                        },
                        "annotations": {
                            "summary": "مصرف حافظه زیاد",
                            "description": "مصرف حافظه صادرکننده از بودجه عبور کرده است",
                        },
                    },
                ],
            }
        ]
        document = {"groups": groups}
        _dump_yaml(path, document)

    def write_error_rules(self, path: Path) -> None:
        groups = [
            {
                "name": "importtosabt-errors",
                "interval": "30s",
                "rules": [
                    {
                        "alert": "ImportToSabtExporterErrors",
                        "expr": "rate(importtosabt_export_errors_total[5m]) > 0",
                        "for": "2m",
                        "labels": {
                            "severity": "warning",
                            "service": "import_to_sabt",
                            "category": "exporter_errors",
                        },
                        "annotations": {
                            "summary": "خطا در صادرکننده",
                            "description": "نرخ خطا در صادرکننده از صفر بیشتر است",
                        },
                    },
                    {
                        "alert": "ImportToSabtRetriesExhausted",
                        "expr": "increase(importtosabt_retry_exhausted_total[10m]) > 0",
                        "for": "1m",
                        "labels": {
                            "severity": "critical",
                            "service": "import_to_sabt",
                            "category": "retry_exhaustion",
                        },
                        "annotations": {
                            "summary": "همه تلاش‌ها مصرف شد",
                            "description": "تلاش مجدد به اتمام رسیده است",
                        },
                    },
                    {
                        "alert": "ImportToSabtRateLimitSpikes",
                        "expr": "increase(importtosabt_rate_limit_rejections_total[5m]) > 20",
                        "for": "5m",
                        "labels": {
                            "severity": "warning",
                            "service": "import_to_sabt",
                            "category": "rate_limit",
                        },
                        "annotations": {
                            "summary": "رد درخواست‌های زیاد",
                            "description": "رد شدن درخواست‌ها به دلیل محدودیت نرخ",
                        },
                    },
                ],
            }
        ]
        document = {"groups": groups}
        _dump_yaml(path, document)

    def write_alertmanager_config(self, path: Path) -> None:
        document = {
            "global": {"resolve_timeout": "5m"},
            "route": {
                "group_by": ["service", "severity"],
                "group_wait": "30s",
                "group_interval": "5m",
                "repeat_interval": "2h",
                "receiver": "default",
            },
            "receivers": [
                {
                    "name": "default",
                    "webhook_configs": [
                        {
                            "url": "http://alertmanager-webhook.local/alerts",
                            "send_resolved": True,
                            "http_config": {"follow_redirects": False},
                        }
                    ],
                }
            ],
            "templates": [],
            "labels": {
                "generated_at": self._clock().isoformat(),
            },
        }
        _dump_yaml(path, document)


def _latency_alert(*, name: str, path: str, threshold: float, summary: str, slo: str) -> dict[str, object]:
    return {
        "alert": name,
        "expr": (
            "histogram_quantile(0.95, "
            f"sum(rate(http_request_duration_seconds_bucket{{path=\"{path}\"}}[5m])) by (le)) > {threshold}"
        ),
        "for": "5m",
        "labels": {
            "severity": "warning",
            "service": "import_to_sabt",
            "budget": f"p95_lt_{int(threshold * 1000)}ms",
            "slo": slo,
        },
        "annotations": {
            "summary": summary,
            "description": "پاسخ‌گویی از آستانه فراتر رفته است",
        },
    }


def _dump_yaml(path: Path, payload: dict[str, object]) -> None:
    yaml_bytes = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        indent=2,
        default_flow_style=False,
    ).encode("utf-8")
    atomic_write(Path(path), yaml_bytes)


__all__ = ["AlertCatalog"]
