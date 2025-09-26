"""CLI for streaming Excel/CSV normalization."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable, Sequence

from src.api.excel_io import (
    DEFAULT_MEMORY_LIMIT,
    ExcelMemoryError,
    HAS_OPENPYXL,
    iter_csv_rows,
    iter_xlsx_rows,
    sanitize_cell,
    write_csv,
    write_xlsx,
)


def _read_rows_from_stdin() -> Iterable[Sequence[str]]:
    reader = csv.reader(sys.stdin)
    for row in reader:
        yield [sanitize_cell(cell) for cell in row]


def cmd_export(args: argparse.Namespace) -> int:
    rows = _read_rows_from_stdin()
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "csv":
        with output.open("wb") as buffer:
            write_csv(rows, stream=buffer)
    else:
        if not HAS_OPENPYXL:
            raise SystemExit("install excel extra to export XLSX files")
        try:
            payload = write_xlsx(
                rows,
                sheet_name=args.sheet,
                memory_limit_bytes=args.memory_limit,
            )
        except ExcelMemoryError as exc:
            raise SystemExit(str(exc)) from exc
        output.write_bytes(payload)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if args.format == "csv":
        with path.open("r", encoding="utf-8-sig") as stream:
            rows = iter_csv_rows(stream)
            for row in rows:
                print(",".join(row.cells))
    else:
        if not HAS_OPENPYXL:
            raise SystemExit("install excel extra to import XLSX files")
        with path.open("rb") as stream:
            for row in iter_xlsx_rows(stream, sheet=args.sheet):
                print(",".join(row.cells))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ابزار کار با فایل‌های Excel/CSV فارسی")
    sub = parser.add_subparsers(dest="command", required=True)

    export_cmd = sub.add_parser("export", help="نوشتن خروجی نرمال‌سازی‌شده")
    export_cmd.add_argument("--out", required=True, help="مسیر خروجی")
    export_cmd.add_argument("--format", choices={"csv", "xlsx"}, default="csv")
    export_cmd.add_argument("--sheet", default="Sheet1")
    export_cmd.add_argument(
        "--memory-limit",
        type=int,
        default=DEFAULT_MEMORY_LIMIT,
        help="حداکثر حجم مجاز خروجی (بایت)",
    )
    export_cmd.set_defaults(func=cmd_export)

    import_cmd = sub.add_parser("import", help="خواندن فایل و چاپ خروجی CSV")
    import_cmd.add_argument("path", help="مسیر فایل ورودی")
    import_cmd.add_argument("--format", choices={"csv", "xlsx"}, default="csv")
    import_cmd.add_argument("--sheet", default="Sheet1")
    import_cmd.set_defaults(func=cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
