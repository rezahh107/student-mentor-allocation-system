from __future__ import annotations

from pathlib import Path

import pytest

from repo_auditor_lite.middleware_check import REQUIRED_ORDER, infer_middleware_order


def test_middleware_order_success(clean_state) -> None:
    sample_path = Path(__file__).resolve().parents[1] / "samples" / "app.py"
    order = infer_middleware_order(sample_path)
    assert order == REQUIRED_ORDER


def test_middleware_order_failure_message() -> None:
    bad_source = """
from fastapi import FastAPI

class RateLimitMiddleware: ...
class IdempotencyMiddleware: ...
class AuthMiddleware: ...

app = FastAPI()
app.add_middleware(AuthMiddleware)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(RateLimitMiddleware)
"""
    with pytest.raises(ValueError) as excinfo:
        infer_middleware_order(bad_source)
    assert "RateLimit" in str(excinfo.value)
    assert "Auth" in str(excinfo.value)
