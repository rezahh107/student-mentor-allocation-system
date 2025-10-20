"""Minimal FastAPI stub for tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass
class _Middleware:
    cls: type


class FastAPI:
    def __init__(self, **_: Any) -> None:
        self.user_middleware: List[_Middleware] = []
        self.routes: Dict[str, Callable] = {}

    def add_middleware(self, middleware_cls: type, **_: Any) -> None:
        self.user_middleware.append(_Middleware(cls=middleware_cls))

    def get(self, path: str) -> Callable[[Callable], Callable]:
        def decorator(func: Callable) -> Callable:
            self.routes[path] = func
            return func

        return decorator
