"""Production-friendly ASGI entrypoint."""

from __future__ import annotations

from sma.phase6_import_to_sabt.app.app_factory import create_application

app = create_application()
