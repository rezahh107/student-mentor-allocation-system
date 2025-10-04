"""Minimal admin CLI for managing hardened API keys."""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Column, MetaData, String, Table, create_engine, select, update
from sqlalchemy.sql import insert

from src.core.clock import Clock
from src.hardened_api.observability import hash_national_id


@dataclass(slots=True)
class CLIConfig:
    database_url: str
    api_key_salt: str


def create_tables(engine) -> None:
    metadata = MetaData()
    Table(
        "api_keys",
        metadata,
        Column("name", String(128)),
        Column("key_hash", String(64), unique=True),
        Column("expires_at", String(32)),
        Column("revoked_at", String(32)),
    )
    metadata.create_all(engine, checkfirst=True)


def list_keys(config: CLIConfig) -> list[tuple[str, str, str | None, str | None]]:
    engine = create_engine(config.database_url)
    metadata = MetaData()
    table = Table("api_keys", metadata, autoload_with=engine)
    with engine.begin() as conn:
        rows = conn.execute(select(table.c.name, table.c.key_hash, table.c.expires_at, table.c.revoked_at)).all()
    return [(row.name, row.key_hash, row.expires_at, row.revoked_at) for row in rows]


def _format_expiry(hours: int | None, *, clock: Clock) -> str | None:
    if hours is None:
        return None
    return (clock.now() + timedelta(hours=hours)).isoformat()


def create_key(
    name: str,
    *,
    config: CLIConfig,
    expires_in_hours: int | None = None,
    clock: Clock | None = None,
) -> str:
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
    metadata.create_all(engine, checkfirst=True)
    active_clock = clock or Clock.for_tehran()
    token = secrets.token_urlsafe(32)
    hashed = hash_national_id(token, salt=config.api_key_salt)
    expires_at = _format_expiry(expires_in_hours, clock=active_clock)
    with engine.begin() as conn:
        conn.execute(
            insert(table).values(
                name=name,
                key_hash=hashed,
                expires_at=expires_at,
                revoked_at=None,
            )
        )
    return token


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="API key management")
    parser.add_argument("command", choices=["list", "create", "revoke"])
    parser.add_argument("--name")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--api-key-salt", default=os.getenv("API_KEY_SALT", "seed-salt"))
    parser.add_argument("--expires-in-hours", type=int, default=None)
    parser.add_argument("--key-hash", help="Hash of API key to revoke")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")
    config = CLIConfig(database_url=args.database_url, api_key_salt=args.api_key_salt)
    clock = Clock.for_tehran()
    if args.command == "list":
        rows = list_keys(config)
        for name, key_hash, expires_at, revoked_at in rows:
            print(f"{name}: {key_hash} | expires_at={expires_at or '-'} | revoked_at={revoked_at or '-'}")
        return 0
    if args.command == "create":
        if not args.name:
            raise SystemExit("--name is required for create")
        token = create_key(
            args.name,
            config=config,
            expires_in_hours=args.expires_in_hours,
            clock=clock,
        )
        print(token)
        return 0
    if args.command == "revoke":
        if not args.key_hash:
            raise SystemExit("--key-hash is required for revoke")
        engine = create_engine(config.database_url)
        metadata = MetaData()
        table = Table("api_keys", metadata, autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(
                update(table)
                .where(table.c.key_hash == args.key_hash)
                .values(revoked_at=clock.now().isoformat())
            )
        print("revoked")
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
