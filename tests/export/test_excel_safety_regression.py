from __future__ import annotations

from datetime import datetime
from pathlib import Path

from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic
from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.security.signer import DualKeySigner, SigningKeyDefinition, SigningKeySet
from src.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from src.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def test_formula_injection_guard(tmp_path: Path) -> None:
    destination = tmp_path / "guard.csv"
    rows = [
        {"name": "=SUM(A1:A2)", "value": "123"},
        {"name": "+HACK", "value": "456"},
        {"name": "@cmd", "value": "789"},
        {"name": " -trim ", "value": "000"},
    ]

    write_csv_atomic(
        destination,
        rows,
        header=["name", "value"],
        sensitive_fields=["value"],
    )

    content = destination.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[1].startswith("'"), content
    assert content.count("'=") >= 1, content
    assert content.count("'+") >= 1, content
    assert content.count("'@") >= 1, content


def test_always_quote_and_formula_guard(tmp_path: Path) -> None:
    registry = CollectorRegistry()
    metrics = build_import_export_metrics(registry)
    clock = FixedClock(datetime(2024, 1, 1, 0, 0, tzinfo=ZoneInfo("Asia/Baku")))
    signer = DualKeySigner(
        keys=SigningKeySet([SigningKeyDefinition("TEST", "S" * 48, "active")]),
        clock=clock,
        metrics=metrics,
        default_ttl_seconds=600,
    )
    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path,
        clock=clock,
        metrics=metrics,
        data_provider=lambda year, center: [
            {"student": "=SUM(A1:A2)", "score": 19.5},
            {"student": "+HACK", "score": 18.0},
        ],
        signed_url_provider=signer,
        signed_url_ttl_seconds=300,
    )

    record = workflow.create_export(year=1402, center=101, file_format="xlsx")
    fetched = workflow.get_export(record.id)
    assert fetched is not None
    urls = workflow.build_signed_urls(fetched)
    assert urls and urls[0]["url"].startswith("/download?")

    safety = fetched.manifest["excel_safety"]
    assert safety["normalized"] is True
    assert safety["formula_guard"] is True
    assert all(entry["name"].endswith(".xlsx") for entry in fetched.manifest["files"])
