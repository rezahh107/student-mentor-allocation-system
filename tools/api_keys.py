"""Admin CLI for managing API keys."""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.infrastructure.persistence.models import APIKeyModel, Base


def _hash_key(value: str, salt: str) -> str:
    digest = hashlib.sha256()
    digest.update((salt + value).encode("utf-8"))
    return digest.hexdigest()


def _open_session(database_url: str) -> Session:
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, future=True)


def cmd_create(args: argparse.Namespace) -> int:
    session = _open_session(args.database_url)
    try:
        value = args.value or secrets.token_urlsafe(args.length)
        if len(value) < 16:
            raise SystemExit("API key must be at least 16 characters")
        salt = secrets.token_hex(16)
        prefix = value[:16]
        record = APIKeyModel(
            name=args.name,
            key_prefix=prefix,
            key_hash=_hash_key(value, salt),
            salt=salt,
            scopes=",".join(sorted(set(args.scopes or []))),
            is_active=True,
            created_at=datetime.utcnow(),
            rotation_hint=args.hint or "",
        )
        session.add(record)
        session.commit()
        print(value)
    finally:
        session.close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    session = _open_session(args.database_url)
    try:
        stmt = select(APIKeyModel).order_by(APIKeyModel.created_at.desc())
        for record in session.execute(stmt).scalars():
            print(
                "\t".join(
                    filter(
                        None,
                        [
                            str(record.id),
                            record.name,
                            record.key_prefix,
                            "فعال" if record.is_active else "غیرفعال",
                            record.scopes,
                            record.created_at.isoformat() if record.created_at else "",
                            record.last_used_at.isoformat() if record.last_used_at else "",
                            record.disabled_at.isoformat() if record.disabled_at else "",
                            record.rotation_hint or "",
                        ],
                    )
                )
            )
    finally:
        session.close()
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    session = _open_session(args.database_url)
    try:
        stmt = select(APIKeyModel).where(APIKeyModel.key_prefix == args.key_prefix)
        record = session.execute(stmt).scalar_one_or_none()
        if record is None:
            raise SystemExit("key prefix not found")
        record.is_active = False
        record.disabled_at = datetime.utcnow()
        session.add(record)
        session.commit()
    finally:
        session.close()
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    session = _open_session(args.database_url)
    try:
        record = session.get(APIKeyModel, args.key_id)
        if record is None:
            raise SystemExit("key id not found")
        value = args.value or secrets.token_urlsafe(args.length)
        if len(value) < 16:
            raise SystemExit("API key must be at least 16 characters")
        new_salt = secrets.token_hex(16)
        record.key_prefix = value[:16]
        record.key_hash = _hash_key(value, new_salt)
        record.salt = new_salt
        record.last_used_at = None
        record.disabled_at = None
        record.is_active = True
        record.rotation_hint = args.hint or ""
        session.add(record)
        session.commit()
        print(value)
    finally:
        session.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="مدیریت کلیدهای API")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "sqlite:///allocation.db"),
        help="آدرس پایگاه‌داده",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_cmd = sub.add_parser("create", help="ساخت کلید جدید")
    create_cmd.add_argument("name", help="نام کلید")
    create_cmd.add_argument("--scope", dest="scopes", action="append", default=[], help="دامنه دسترسی")
    create_cmd.add_argument("--value", help="مقدار دلخواه کلید")
    create_cmd.add_argument("--length", type=int, default=40, help="طول کلید تصادفی")
    create_cmd.add_argument("--hint", help="راهنمای چرخش", default="")
    create_cmd.set_defaults(func=cmd_create)

    list_cmd = sub.add_parser("list", help="نمایش کلیدها")
    list_cmd.set_defaults(func=cmd_list)

    revoke_cmd = sub.add_parser("revoke", help="غیرفعال کردن کلید")
    revoke_cmd.add_argument("key_prefix", help="پیشوند کلید")
    revoke_cmd.set_defaults(func=cmd_revoke)

    rotate_cmd = sub.add_parser("rotate", help="چرخش کلید موجود")
    rotate_cmd.add_argument("key_id", type=int, help="شناسه کلید")
    rotate_cmd.add_argument("--value", help="مقدار جدید در صورت نیاز")
    rotate_cmd.add_argument("--length", type=int, default=40, help="طول کلید تصادفی")
    rotate_cmd.add_argument("--hint", help="راهنمای چرخش", default="")
    rotate_cmd.set_defaults(func=cmd_rotate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
