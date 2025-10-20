"""CLI for exporting allocation data to CSV/XLSX."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sma.tools.export.csv_exporter import export_allocations_to_csv
from sma.tools.export.xlsx_exporter import export_allocations_to_xlsx

logger = logging.getLogger("export_cli")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="خروجی گرفتن از تخصیص‌ها")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "sqlite:///allocation.db"))
    parser.add_argument("--output", required=True, help="مسیر فایل خروجی")
    parser.add_argument("--format", choices=("csv", "xlsx"), default="csv")
    parser.add_argument("--bom", action="store_true", help="افزودن BOM برای CSV")
    parser.add_argument("--crlf", action="store_true", help="پایان خط CRLF در CSV")
    parser.add_argument("--chunk-size", type=int, default=1000, help="اندازه دسته برای خواندن")
    parser.add_argument("--no-excel-safe", dest="excel_safe", action="store_false", help="غیرفعال‌سازی محافظ فرمول")
    parser.set_defaults(excel_safe=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = create_engine(args.database_url, future=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = SessionFactory()
    output = Path(args.output)

    try:
        if args.format == "csv":
            if not args.bom:
                logger.warning(
                    "فایل CSV بدون BOM ممکن است در Excel به‌درستی نمایش داده نشود",
                    extra={"کد": "EXPORT_BOM_REQUIRED"},
                )
            export_allocations_to_csv(
                session=session,
                output=output,
                bom=args.bom,
                crlf=args.crlf,
                chunk_size=args.chunk_size,
                excel_safe=args.excel_safe,
            )
        else:
            export_allocations_to_xlsx(
                session=session,
                output=output,
                chunk_size=args.chunk_size,
                excel_safe=args.excel_safe,
            )
        logger.info("خروجی با موفقیت تولید شد", extra={"کد": "EXPORT_DONE", "مسیر": str(output)})
        return 0
    except Exception as exc:  # pragma: no cover - CLI guard
        logger.exception("خروجی گرفتن با خطا متوقف شد", extra={"کد": "EXPORT_FAILED"})
        print(f"EXPORT_FAILED|{exc}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
