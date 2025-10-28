from sma.phase6_import_to_sabt.app.app_factory import create_application

_REDIS = '{"dsn":"redis://127.0.0.1:6379/0"}'
_DATABASE = '{"dsn":"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"}'
_AUTH = '{"service_token":"dev-admin","metrics_token":"dev-metrics"}'


def test_docs_public_toggle(monkeypatch):
    monkeypatch.setenv("IMPORT_TO_SABT_REDIS", _REDIS)
    monkeypatch.setenv("IMPORT_TO_SABT_DATABASE", _DATABASE)
    monkeypatch.setenv("IMPORT_TO_SABT_AUTH", _AUTH)
    monkeypatch.setenv("IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS", "true")
    app = create_application()
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"
    monkeypatch.delenv("IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS", raising=False)
    app_locked = create_application()
    assert app_locked.docs_url is None
    assert app_locked.redoc_url is None
    assert app_locked.openapi_url is None
