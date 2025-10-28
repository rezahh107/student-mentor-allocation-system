import re

from sma.phase6_import_to_sabt.app.app_factory import create_application

_REDIS = '{"dsn":"redis://127.0.0.1:6379/0"}'
_DATABASE = '{"dsn":"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"}'
_AUTH = '{"service_token":"dev-admin","metrics_token":"dev-metrics"}'


def _norm(name: str) -> str:
    return name.lower()


def test_middleware_order_ratelimit_idempotency_auth(monkeypatch):
    monkeypatch.setenv("IMPORT_TO_SABT_REDIS", _REDIS)
    monkeypatch.setenv("IMPORT_TO_SABT_DATABASE", _DATABASE)
    monkeypatch.setenv("IMPORT_TO_SABT_AUTH", _AUTH)
    app = create_application()
    names = [_norm(m.cls.__name__) for m in getattr(app, "user_middleware", [])]
    joined = " > ".join(names)

    def find_idx(pat):
        for i, n in enumerate(names):
            if re.search(pat, n):
                return i
        return -1

    i_rl = find_idx(r"rate.?limit")
    i_id = find_idx(r"idempot")
    i_au = find_idx(r"auth")
    assert all(x >= 0 for x in (i_rl, i_id, i_au)), f"«میان‌افزارها یافت نشدند» names={joined}"
    assert i_rl < i_id < i_au, f"«ترتیب میان‌افزار نادرست است (باید RateLimit→Idempotency→Auth)» names={joined}"
