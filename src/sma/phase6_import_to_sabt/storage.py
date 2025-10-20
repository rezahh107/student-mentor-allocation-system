from __future__ import annotations

import os
from pathlib import Path

from sma.phase6_import_to_sabt.models import StorageBackend


class LocalStorageBackend(StorageBackend):
    def ensure_directory(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def cleanup_partials(self, path: str) -> None:
        directory = Path(path)
        if not directory.exists():
            return
        for item in directory.glob("*.part"):
            try:
                item.unlink()
            except FileNotFoundError:
                continue
