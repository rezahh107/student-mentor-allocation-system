from __future__ import annotations

import ast
from pathlib import Path
from typing import List

REQUIRED_ORDER = ["RateLimit", "Idempotency", "Auth"]


def _load_source(app_or_source: str | Path) -> str:
    if isinstance(app_or_source, Path):
        return app_or_source.read_text(encoding="utf-8")
    candidate = Path(app_or_source)
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    return str(app_or_source)


class _MiddlewareVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.app_names: set[str] = set()
        self.order: List[str] = []

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: D401
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id == "FastAPI":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.app_names.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: D401
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "add_middleware"
            and isinstance(func.value, ast.Name)
            and func.value.id in self.app_names
            and node.args
        ):
            name = _extract_name(node.args[0])
            if name:
                self.order.append(name)
        self.generic_visit(node)


def _extract_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _extract_name(node.func)
    return None


def _canonical(name: str) -> str:
    if name.endswith("Middleware"):
        name = name[:-10]
    return name


def infer_middleware_order(app_or_source: str | Path) -> List[str]:
    source = _load_source(app_or_source)
    tree = ast.parse(source)
    visitor = _MiddlewareVisitor()
    visitor.visit(tree)
    order = [_canonical(item) for item in visitor.order]
    if not order:
        raise ValueError("زنجیرهٔ میان‌افزار شناسایی نشد.")
    if order != REQUIRED_ORDER:
        raise ValueError(
            "ترتیب میان‌افزار نامعتبر است؛ انتظار می‌رود RateLimit → Idempotency → Auth باشد."
        )
    return order


__all__ = ["infer_middleware_order", "REQUIRED_ORDER"]
