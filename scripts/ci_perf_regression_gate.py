#!/usr/bin/env python3
"""Compare collected performance metrics with the committed baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CURRENT = Path("reports/perf.json")
DEFAULT_BASELINE = Path("reports/perf_baseline.json")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(f"❌ فایل {path} یافت نشد؛ ابتدا گزارش کارایی را تولید کنید.")
        raise SystemExit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        print(f"❌ فایل {path} معتبر نیست: {exc}.")
        raise SystemExit(1)


def _as_float(payload: Dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if value is None:
        print(f"❌ مقدار {key} در گزارش یافت نشد.")
        raise SystemExit(1)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        print(f"❌ مقدار {key} قابل تبدیل به عدد نیست: {exc}.")
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Performance regression gate")
    parser.add_argument("--current", default=str(DEFAULT_CURRENT), help="مسیر گزارش اجرای فعلی")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="مسیر گزارش مبنا")
    parser.add_argument("--tolerance", type=float, default=0.05, help="مجاز برای رشد (نسبت اعشاری)")
    args = parser.parse_args()

    current = _load_json(Path(args.current))
    baseline = _load_json(Path(args.baseline))

    p95_current = _as_float(current, "p95_ms")
    p95_baseline = _as_float(baseline, "p95_ms")
    mem_current = _as_float(current, "mem_mb_peak")
    mem_baseline = _as_float(baseline, "mem_mb_peak")

    allowed_p95 = p95_baseline * (1 + args.tolerance)
    allowed_mem = mem_baseline * (1 + args.tolerance)

    regression_messages = []
    if p95_current > allowed_p95:
        regression_messages.append(
            f"p95 فعلی {p95_current:.2f}ms از سقف {allowed_p95:.2f}ms عبور کرده است."
        )
    if mem_current > allowed_mem:
        regression_messages.append(
            f"مصرف حافظه فعلی {mem_current:.2f}MB از سقف {allowed_mem:.2f}MB بیشتر است."
        )

    if regression_messages:
        joined = "؛ ".join(regression_messages)
        print(f"❌ پسرفت کارایی: {joined}")
        raise SystemExit(1)

    print(
        json.dumps(
            {
                "پیام": "✅ کارایی مطابق مبنا است.",
                "p95_ms": round(p95_current, 2),
                "mem_mb_peak": round(mem_current, 2),
                "مبنا": {
                    "p95_ms": round(p95_baseline, 2),
                    "mem_mb_peak": round(mem_baseline, 2),
                    "clock": baseline.get("clock", "Asia/Tehran"),
                },
                "تلرانس": args.tolerance,
                "clock": current.get("clock", "Asia/Tehran"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
