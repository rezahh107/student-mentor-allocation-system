from __future__ import annotations

from http import HTTPStatus

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from sma.phase6_import_to_sabt.app.app_factory import create_application

_DEFERRAL_MESSAGE = (
    "Auth allow-all mode must keep documentation endpoints public during local testing."
)


def test_docs_and_redoc_are_public_when_flag_enabled(monkeypatch: MonkeyPatch) -> None:
    """Ensure docs endpoints stay public while auth middleware allows all traffic."""

    monkeypatch.setenv("IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS", "true")

    app = create_application()

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        redoc_response = client.get("/redoc")

    assert docs_response.status_code == HTTPStatus.OK, _DEFERRAL_MESSAGE
    assert redoc_response.status_code == HTTPStatus.OK, _DEFERRAL_MESSAGE
