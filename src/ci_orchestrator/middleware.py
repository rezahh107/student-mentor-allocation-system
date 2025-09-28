from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class Middleware:
    name: str
    priority: int


def build_middleware_chain() -> List[Middleware]:
    return [
        Middleware(name="RateLimit", priority=10),
        Middleware(name="Idempotency", priority=20),
        Middleware(name="Auth", priority=30),
    ]


def middleware_order() -> list[str]:
    chain = sorted(build_middleware_chain(), key=lambda item: item.priority)
    return [item.name for item in chain]
