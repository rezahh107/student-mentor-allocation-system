from __future__ import annotations

import json
import secrets
from collections import deque
from datetime import timedelta
from typing import Any, Deque, Mapping
from uuid import uuid4
from urllib.parse import parse_qs

import httpx

from auth.utils import encode_base64url


class MockOIDCProvider:
    def __init__(self, *, clock) -> None:
        self.clock = clock
        self.issuer = "https://mock-oidc.local"
        self.client_id = "mock-client"
        self.client_secret = "mock-secret"
        self.scopes = ("openid", "profile")
        self.token_endpoint = f"{self.issuer}/token"
        self.jwks_endpoint = f"{self.issuer}/jwks"
        self.auth_endpoint = f"{self.issuer}/authorize"
        self.transport = httpx.MockTransport(self._handle)
        self._codes: dict[str, Mapping[str, Any]] = {}
        self._key = {"kty": "oct", "kid": "mock-key", "k": self.client_secret}
        self._signing_secret = self.client_secret
        self._jwks_current: list[Mapping[str, Any]] = [self._key]
        self._jwks_queue: Deque[list[Mapping[str, Any]]] = deque()

    def issue_code(self, claims: Mapping[str, Any], *, code: str | None = None) -> str:
        issued = {"sub": claims.get("sub", uuid4().hex)}
        issued.update(claims)
        key = code or secrets.token_hex(8)
        self._codes[key] = issued
        return key

    def env(self) -> dict[str, str]:
        return {
            "SSO_ENABLED": "true",
            "SSO_SESSION_TTL_SECONDS": "900",
            "SSO_BLUE_GREEN_STATE": "green",
            "OIDC_CLIENT_ID": self.client_id,
            "OIDC_CLIENT_SECRET": self.client_secret,
            "OIDC_ISSUER": self.issuer,
            "OIDC_SCOPES": "openid profile",
            "OIDC_TOKEN_ENDPOINT": self.token_endpoint,
            "OIDC_AUTH_ENDPOINT": self.auth_endpoint,
            "OIDC_JWKS_ENDPOINT": self.jwks_endpoint,
        }

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            form = parse_qs(request.content.decode())
            code = form.get("code", [None])[0]
            if not code or code not in self._codes:
                return httpx.Response(400, json={"error": "invalid_grant"})
            claims = self._codes.pop(code)
            id_token = self._build_token(claims)
            return httpx.Response(200, json={"id_token": id_token})
        if request.url.path.endswith("/jwks"):
            if self._jwks_queue:
                self._jwks_current = self._jwks_queue.popleft()
            return httpx.Response(200, json={"keys": list(self._jwks_current)})
        if request.url.path.endswith("/authorize"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "not_found"})

    def _build_token(self, claims: Mapping[str, Any]) -> str:
        header = {"alg": "HS256", "kid": self._key["kid"]}
        now = self.clock.now()
        payload = {
            "iss": self.issuer,
            "aud": self.client_id,
            "exp": (now + timedelta(minutes=5)).timestamp(),
            "nbf": (now - timedelta(minutes=1)).timestamp(),
            "sub": claims.get("sub"),
            "role": claims.get("role"),
            "center_scope": claims.get("center_scope"),
        }
        if "userinfo" in claims:
            payload["userinfo"] = claims["userinfo"]
        header_segment = encode_base64url(json.dumps(header).encode())
        payload_segment = encode_base64url(json.dumps(payload).encode())
        signing_input = f"{header_segment}.{payload_segment}".encode()
        signature = self._sign(signing_input)
        signature_segment = encode_base64url(signature)
        return f"{header_segment}.{payload_segment}.{signature_segment}"

    def _sign(self, payload: bytes) -> bytes:
        import hmac
        import hashlib

        digest = hmac.new(self._signing_secret.encode(), payload, hashlib.sha256).digest()
        return digest

    def rotate_signing_key(self, kid: str, secret: str, *, publish: bool = False) -> None:
        self._key = {"kty": "oct", "kid": kid, "k": secret}
        self._signing_secret = secret
        if publish:
            self._jwks_current = [self._key]

    def queue_jwks(self, payloads: list[list[Mapping[str, Any]]]) -> None:
        self._jwks_queue = deque(payloads)

    def publish_jwks(self, keys: list[Mapping[str, Any]]) -> None:
        self._jwks_current = list(keys)


__all__ = ["MockOIDCProvider"]
