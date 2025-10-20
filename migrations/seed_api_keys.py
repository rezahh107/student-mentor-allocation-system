"""Seed script to insert initial API keys for hardened API."""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from dataclasses import dataclass

from sqlalchemy import Column, MetaData, String, Table, create_engine
from sqlalchemy.sql import insert

from sma.hardened_api.observability import hash_national_id


@dataclass(slots=True)
class SeedConfig:
    database_url: str
    api_key_salt: str


def generate_api_key(name: str, *, salt: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    hashed = hash_national_id(token, salt=salt)
    return token, hashed


def seed(name: str, *, config: SeedConfig) -> str:
    engine = create_engine(config.database_url)
    metadata = MetaData()
    table = Table(
        "api_keys",
        metadata,
        Column("name", String(128)),
        Column("key_hash", String(64)),
        Column("expires_at", String(32)),
        Column("revoked_at", String(32)),
    )
    token, hashed = generate_api_key(name, salt=config.api_key_salt)
    with engine.begin() as conn:
        conn.execute(
            insert(table).values(
                name=name,
                key_hash=hashed,
                expires_at=None,
                revoked_at=None,
            )
        )
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed API keys")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--api-key-salt", default=os.getenv("API_KEY_SALT", "seed-salt"))
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("DATABASE_URL must be provided")
    config = SeedConfig(database_url=args.database_url, api_key_salt=args.api_key_salt)
    token = seed(args.name, config=config)
    print(token)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
