"""Production-friendly ASGI entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    root = Path(__file__).resolve().parent
    src = root / "src"
    for candidate in (src, root):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


_ensure_src_on_path()

from sma.phase6_import_to_sabt.app.app_factory import create_application

app = create_application()
