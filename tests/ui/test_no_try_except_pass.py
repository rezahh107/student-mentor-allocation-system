"""Ensure no silent ``except Exception: pass`` remains in the UI layer."""
from __future__ import annotations

from pathlib import Path
import re


_PATTERN = re.compile(r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*(?:\n\s*)*pass\b")


def test_no_try_except_pass_in_ui() -> None:
    ui_dir = Path("src/ui")
    offenders: list[str] = []
    for path in ui_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _PATTERN.search(text):
            offenders.append(str(path))
    assert not offenders, f"بلوک‌های except Exception: pass در فایل‌های UI یافت شد: {offenders}"
