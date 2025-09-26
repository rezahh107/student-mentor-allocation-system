"""optional seed api keys from environment"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "007_seed_api_keys"
down_revision = "006_api_keys_table"
branch_labels = None
depends_on = None


def _hash_key(value: str, salt: str) -> str:
    digest = hashlib.sha256()
    digest.update((salt + value).encode("utf-8"))
    return digest.hexdigest()


def upgrade() -> None:
    payload = os.getenv("ALLOC_API_SEED_KEYS")
    if not payload:
        return

    try:
        records = json.loads(payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - migration guard
        raise RuntimeError("ALLOC_API_SEED_KEYS must be valid JSON list") from exc

    if not isinstance(records, list):
        raise RuntimeError("ALLOC_API_SEED_KEYS must be a JSON list of objects")

    for entry in records:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "seed")
        value = entry.get("value")
        if not value:
            continue
        scopes = ",".join(sorted(set(map(str, entry.get("scopes", [])))))
        salt = entry.get("salt") or secrets.token_hex(16)
        key_prefix = value[:16]
        key_hash = _hash_key(value, salt)
        expires_at = entry.get("expires_at")
        params: dict[str, object] = {
            "name": name,
            "key_prefix": key_prefix,
            "key_hash": key_hash,
            "salt": salt,
            "scopes": scopes,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else None,
            "last_used_at": None,
        }
        insert = sa.text(
            """
            INSERT INTO api_keys
            (name, key_prefix, key_hash, salt, scopes, is_active, created_at, expires_at, last_used_at)
            VALUES (:name, :key_prefix, :key_hash, :salt, :scopes, :is_active, :created_at, :expires_at, :last_used_at)
            ON CONFLICT(key_prefix) DO NOTHING
            """
        )
        op.execute(insert, params)


def downgrade() -> None:
    # No-op for seeded keys
    pass
