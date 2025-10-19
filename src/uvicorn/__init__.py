"""Minimal Uvicorn stub for tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Config:
    app: Any
    host: str
    port: int
    lifespan: str
    loop: str

    def load(self) -> None:
        # In the real implementation this validates the configuration.
        if self.app is None:
            raise RuntimeError("app missing")
