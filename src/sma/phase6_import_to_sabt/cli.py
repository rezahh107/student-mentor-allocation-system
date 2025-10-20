from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Sequence

from sma.phase6_import_to_sabt.job_runner import ExportJobRunner
from sma.phase6_import_to_sabt.models import ExportDeltaWindow, ExportFilters, ExportOptions


def create_cli(runner: ExportJobRunner):
    parser = argparse.ArgumentParser(description="Phase-6 ImportToSabt exporter")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run a full export")
    run_parser.add_argument("--year", type=int, required=True)
    run_parser.add_argument("--center", type=int)
    run_parser.add_argument("--chunk-size", type=int, default=50_000)
    run_parser.add_argument("--bom", action="store_true")
    run_parser.add_argument("--excel-mode", dest="excel_mode", action="store_true", default=True)
    run_parser.add_argument("--no-excel-mode", dest="excel_mode", action="store_false")

    delta_parser = sub.add_parser("delta", help="Run a delta export")
    delta_parser.add_argument("--year", type=int, required=True)
    delta_parser.add_argument("--center", type=int)
    delta_parser.add_argument("--created-at", required=True)
    delta_parser.add_argument("--id", type=int, required=True)
    delta_parser.add_argument("--chunk-size", type=int, default=50_000)
    delta_parser.add_argument("--bom", action="store_true")
    delta_parser.add_argument("--excel-mode", dest="excel_mode", action="store_true", default=True)
    delta_parser.add_argument("--no-excel-mode", dest="excel_mode", action="store_false")

    return parser


def run_cli(runner: ExportJobRunner, argv: Sequence[str] | None = None) -> int:
    parser = create_cli(runner)
    args = parser.parse_args(argv)
    if args.command == "run":
        filters = ExportFilters(year=args.year, center=args.center)
        options = ExportOptions(chunk_size=args.chunk_size, include_bom=args.bom, excel_mode=args.excel_mode)
    else:
        delta = ExportDeltaWindow(created_at_watermark=datetime.fromisoformat(args.created_at), id_watermark=args.id)
        filters = ExportFilters(year=args.year, center=args.center, delta=delta)
        options = ExportOptions(chunk_size=args.chunk_size, include_bom=args.bom, excel_mode=args.excel_mode)
    job = runner.submit(
        filters=filters,
        options=options,
        idempotency_key=f"cli-{args.year}-{args.center or 'all'}",
        namespace="cli",
        correlation_id="cli",
    )
    runner.await_completion(job.id)
    job = runner.get_job(job.id)
    if job and job.manifest:
        print(json.dumps({"job_id": job.id, "total_rows": job.manifest.total_rows}, ensure_ascii=False))
    return 0


__all__ = ["create_cli", "run_cli"]
