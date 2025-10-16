"""Environment verification script for Tailored v2.4."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_SECTIONS = (
    "Middleware",  # AGENTS.md::Middleware Order
    "Excel",       # AGENTS.md::Excel safety instructions
    "Determinism", # AGENTS.md::Determinism
    "Evidence",    # AGENTS.md::Evidence Model
)

PERSIAN_FAIL_PREFIX = "اعتبارسنجی محیط شکست خورد؛ لطفاً پیام را بررسی کنید."
PERSIAN_SUCCESS = "محیط توسعه آماده است."
EN_SUCCESS = "Environment verification succeeded."


def _fail(persian: str, english: str) -> None:
    message = f"{persian} :: {english}"
    print(message, file=sys.stderr)
    sys.exit(1)


def _verify_python() -> None:
    if sys.version_info < (3, 11):
        _fail(
            PERSIAN_FAIL_PREFIX,
            "Python 3.11 or newer is required.",
        )


def _verify_paths() -> None:
    root = Path.cwd()
    for required in ("src", "tests"):
        if not (root / required).is_dir():
            _fail(
                PERSIAN_FAIL_PREFIX,
                f"Missing required directory: {required}",
            )


def _verify_agents() -> None:
    for candidate in (Path("AGENTS.md"), Path("agent.md")):
        if candidate.is_file():
            content = candidate.read_text(encoding="utf-8", errors="ignore")
            missing = [section for section in REQUIRED_SECTIONS if section not in content]
            if missing:
                _fail(
                    PERSIAN_FAIL_PREFIX,
                    f"AGENTS.md missing required sections: {', '.join(missing)}",
                )
            return
    _fail(
        "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید.",
        "AGENTS.md missing at repository root; add agents.md-compliant spec.",
    )


def main() -> None:
    _verify_python()
    _verify_paths()
    _verify_agents()
    print(f"{PERSIAN_SUCCESS} :: {EN_SUCCESS}")


if __name__ == "__main__":
    main()
