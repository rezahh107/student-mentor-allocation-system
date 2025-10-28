import re
from typing import Iterator

import pytest

from sma.phase6_import_to_sabt.app.app_factory import create_application

_REDIS = '{"dsn":"redis://127.0.0.1:6379/0"}'
_DATABASE = '{"dsn":"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"}'
_AUTH = '{"service_token":"dev-admin","metrics_token":"dev-metrics"}'

_ANCHOR = "AGENTS.md::Middleware Order"


def _lower_names(app) -> list[str]:
    return [middleware.cls.__name__.lower() for middleware in getattr(app, "user_middleware", [])]


@pytest.fixture()
def app_under_test(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    monkeypatch.setenv("IMPORT_TO_SABT_REDIS", _REDIS)
    monkeypatch.setenv("IMPORT_TO_SABT_DATABASE", _DATABASE)
    monkeypatch.setenv("IMPORT_TO_SABT_AUTH", _AUTH)
    app = create_application()
    yield app


@pytest.mark.middleware
@pytest.mark.ci
def test_middleware_order_indices(app_under_test) -> None:
    names = _lower_names(app_under_test)
    joined = " > ".join(names)
    idx = {"rl": -1, "id": -1, "auth": -1}
    for i, name in enumerate(names):
        if idx["rl"] < 0 and re.search(r"rate.?limit", name):
            idx["rl"] = i
        if idx["id"] < 0 and re.search(r"idempot", name):
            idx["id"] = i
        if idx["auth"] < 0 and re.search(r"auth", name):
            idx["auth"] = i
    assert all(v >= 0 for v in idx.values()), f"«میان‌افزارها یافت نشدند» names={joined}"
    assert idx["rl"] < idx["id"] < idx["auth"], {"chain": joined, "evidence": _ANCHOR}


@pytest.mark.middleware
def test_middleware_order_unique(app_under_test) -> None:
    names = _lower_names(app_under_test)
    rl_count = sum(1 for name in names if re.search(r"rate.?limit", name))
    id_count = sum(1 for name in names if re.search(r"idempot", name))
    auth_count = sum(1 for name in names if re.search(r"auth", name))
    assert rl_count == 1, f"«RateLimit باید تنها یک‌بار باشد» names={names}"
    assert id_count == 1, f"«Idempotency باید تنها یک‌بار باشد» names={names}"
    assert auth_count == 1, f"«Auth باید تنها یک‌بار باشد» names={names}"
