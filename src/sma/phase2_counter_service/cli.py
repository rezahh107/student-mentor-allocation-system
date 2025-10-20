# -*- coding: utf-8 -*-
"""Command line interface for the counter service."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Iterable, Optional, Sequence

from sma.infrastructure.export.excel_safe import make_excel_safe_writer
from sma.core.clock import Clock, tehran_clock

from . import assign_counter, get_config, get_service
from .backfill import BackfillStats, run_backfill
from .observability import MetricsServer
from .types import BackfillObserver


try:  # pragma: no branch - import guard for coverage stability
    import_module("scripts.post_migration_checks")
except ModuleNotFoundError:  # pragma: no cover - optional in prod builds
    pass


PERSIAN_BOOLEAN = {True: "بله", False: "خیر"}
"""Mapping used to localize boolean values for CSV serialization."""


def _timestamp_suffix(clock: Clock | None = None) -> str:
    """Return an ISO-like timestamp suitable for file names."""

    active_clock = clock or tehran_clock()
    return active_clock.now().strftime("%Y%m%dT%H%M%S")


def _ensure_unique_path(path: Path, *, overwrite: bool, original: Optional[str] = None) -> Path:
    """Resolve a concrete file path for stats CSV output.

    Parameters
    ----------
    path:
        User-supplied path that may point to a file or a directory.
    overwrite:
        When ``True`` existing files are replaced; otherwise the function raises
        :class:`FileExistsError` with a localized explanation.
    original:
        Raw string supplied by the operator. Used to infer directory intent when
        the :class:`~pathlib.Path` instance loses trailing separators.

    Returns
    -------
    Path
        Final path that should be opened for writing.
    """

    candidate = path.expanduser()
    hint = original or str(path)
    looks_like_directory = False

    if candidate.exists():
        looks_like_directory = candidate.is_dir()
    else:
        trailing_sep = hint.endswith((os.sep, "/", "\\"))
        looks_like_directory = trailing_sep or not candidate.suffix

    if looks_like_directory:
        candidate.mkdir(parents=True, exist_ok=True)
        while True:
            suffix = f"{_timestamp_suffix()}_{uuid.uuid4().hex[:6]}"
            resolved = candidate / f"backfill_stats_{suffix}.csv"
            if not resolved.exists():
                return resolved

    parent = candidate.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists():
        if overwrite:
            return candidate
        message = (
            f"فایل خروجی «{candidate}» از قبل وجود دارد؛ برای بازنویسی از --overwrite استفاده کنید."
        )
        raise FileExistsError(message)
    return candidate


def _localized_rows(stats: BackfillStats) -> Iterable[tuple[str, object]]:
    """Yield the localized key/value pairs for stats CSV serialization."""

    return (
        ("total_rows", stats.total_rows),
        ("applied", stats.applied),
        ("reused", stats.reused),
        ("skipped", stats.skipped),
        ("dry_run", PERSIAN_BOOLEAN[stats.dry_run]),
        ("prefix_mismatches", stats.prefix_mismatches),
    )


class StdoutObserver(BackfillObserver):
    """Prints progress for each processed chunk."""

    def on_chunk(self, chunk_index: int, applied: int, reused: int, skipped: int) -> None:
        payload = {
            "chunk": chunk_index,
            "applied": applied,
            "reused": reused,
            "skipped": skipped,
        }
        print(json.dumps(payload, ensure_ascii=False))


def _run_assign(args: argparse.Namespace) -> int:
    try:
        counter = assign_counter(args.national_id, args.gender, args.year_code)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(str(exc), file=sys.stderr)
        return 1
    print(counter)
    return 0


def _run_backfill(args: argparse.Namespace) -> int:
    if args.stats_csv is None and any((args.excel_safe, args.bom, args.crlf, args.quote_all)):
        print("برای استفاده از پرچم‌های CSV باید --stats-csv تعیین شود.", file=sys.stderr)
        return 2
    service = get_service()
    observer: Optional[BackfillObserver]
    if args.verbose and not args.json_only:
        observer = StdoutObserver()
    else:
        observer = None
    stats = run_backfill(
        service,
        Path(args.csv_path),
        chunk_size=args.chunk_size,
        apply=args.apply,
        observer=observer,
    )
    stats_payload = asdict(stats)
    stats_csv_path: Optional[str] = None
    if args.stats_csv:
        try:
            resolved = _write_stats_csv(
                Path(args.stats_csv),
                stats,
                excel_safe=args.excel_safe,
                bom=args.bom,
                crlf=args.crlf,
                quote_all=args.quote_all,
                overwrite=args.overwrite,
                original=args.stats_csv,
                announce=not args.json_only,
            )
            stats_csv_path = str(resolved)
        except OSError as exc:
            print(f"خطا در نوشتن CSV: {exc}", file=sys.stderr)
            print(json.dumps(stats_payload, ensure_ascii=False))
            return 1
    if stats_csv_path is not None:
        stats_payload["stats_csv_path"] = stats_csv_path
    print(json.dumps(stats_payload, ensure_ascii=False))
    return 0


def _write_stats_csv(
    path: Path,
    stats: BackfillStats,
    *,
    excel_safe: bool,
    bom: bool,
    crlf: bool,
    quote_all: bool,
    overwrite: bool,
    original: Optional[str] = None,
    announce: bool = True,
) -> Path:
    resolved = _ensure_unique_path(path, overwrite=overwrite, original=original)
    with resolved.open("w", encoding="utf-8", newline="") as handle:
        writer = make_excel_safe_writer(
            handle,
            bom=bom,
            guard_formulas=excel_safe,
            quote_all=quote_all,
            crlf=crlf,
        )
        writer.writerow(["شاخص", "مقدار"])
        writer.writerows(_localized_rows(stats))
    if announce:
        print(f"گزارش آمار در «{resolved}» ذخیره شد.")
    return resolved


def _run_metrics(args: argparse.Namespace) -> int:
    config = get_config()
    port = args.port or config.metrics_port
    server = MetricsServer()
    server.start(port)
    if args.oneshot:
        server.stop()
        return 0
    duration = args.duration
    try:
        if duration is not None:
            time.sleep(duration)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - manual interrupt
        pass
    finally:
        server.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 2 counter service CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    assign_cmd = sub.add_parser("assign-counter", help="Assign a counter for a single student")
    assign_cmd.add_argument("national_id", help="کد ملی ۱۰ رقمی")
    assign_cmd.add_argument("gender", type=int, choices=(0, 1), help="جنسیت از منبع اصلی داده")
    assign_cmd.add_argument("year_code", help="کد سال دو رقمی")
    assign_cmd.set_defaults(func=_run_assign)

    backfill_cmd = sub.add_parser("backfill", help="Stream CSV backfill")
    backfill_cmd.add_argument("csv_path", help="مسیر فایل CSV ورودی")
    backfill_cmd.add_argument("--chunk-size", type=int, default=500, help="اندازه دسته‌ها")
    backfill_cmd.add_argument("--apply", action="store_true", help="اجرای واقعی به جای dry-run")
    backfill_cmd.add_argument("--verbose", action="store_true", help="چاپ پیشرفت دسته‌ای")
    backfill_cmd.add_argument("--stats-csv", help="ذخیره خلاصهٔ اجرا در فایل CSV")
    backfill_cmd.add_argument("--excel-safe", action="store_true", help="محافظت خروجی CSV برای Excel")
    backfill_cmd.add_argument("--bom", action="store_true", help="افزودن BOM UTF-8 به خروجی")
    backfill_cmd.add_argument("--crlf", action="store_true", help="استفاده از CRLF برای سطرهای CSV")
    backfill_cmd.add_argument("--quote-all", action="store_true", help="قرار دادن کوت برای همهٔ ستون‌ها")
    backfill_cmd.add_argument(
        "--json-only",
        action="store_true",
        help="نمایش فقط JSON نهایی (بدون بنر فارسی)",
    )
    backfill_cmd.add_argument(
        "--overwrite",
        action="store_true",
        help="بازنویسی فایل خروجی در صورت وجود",
    )
    backfill_cmd.set_defaults(func=_run_backfill)

    metrics_cmd = sub.add_parser("serve-metrics", help="اجرای اکسپورتر پرومتئوس")
    metrics_cmd.add_argument("--port", type=int, help="پورت سرویس")
    metrics_cmd.add_argument("--oneshot", action="store_true", help="فقط مقداردهی اولیه و خروج")
    metrics_cmd.add_argument("--duration", type=float, help="خروج خودکار بعد از این مدت (ثانیه)")
    metrics_cmd.set_defaults(func=_run_metrics)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    return int(result)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
