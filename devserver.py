"""Development server entrypoint for ImportToSabt."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT / "src"))

if load_dotenv is not None:
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

from phase6_import_to_sabt.app.app_factory import create_application

app = create_application()
