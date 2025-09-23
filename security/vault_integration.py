# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Optional

try:
    import hvac  # type: ignore
except Exception:  # pragma: no cover
    hvac = None  # type: ignore


class SecretProvider:
    def __init__(self) -> None:
        self._client = None
        if hvac and os.getenv("VAULT_ADDR"):
            client = hvac.Client(url=os.environ["VAULT_ADDR"], token=os.getenv("VAULT_TOKEN"))
            if client.is_authenticated():
                self._client = client

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Try Vault KV v2 at path secret/data/{key}
        if self._client:
            try:
                resp = self._client.secrets.kv.v2.read_secret_version(path=key)
                return resp["data"]["data"].get("value")
            except Exception:
                pass
        return os.getenv(key.upper(), default)

