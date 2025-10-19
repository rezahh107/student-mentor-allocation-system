from __future__ import annotations

from pathlib import Path

from tools.reqs_doctor import MIDDLEWARE_ORDER, MIDDLEWARE_ORDER_DOC


def test_middleware_order_documented():
    order = " → ".join(MIDDLEWARE_ORDER)
    assert order == MIDDLEWARE_ORDER_DOC
    agents_text = Path("AGENTS.md").read_text(encoding="utf-8")
    assert order in agents_text, f"Middleware order mismatch: {order}"
