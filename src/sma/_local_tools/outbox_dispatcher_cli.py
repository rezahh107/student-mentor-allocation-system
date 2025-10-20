"""CLI worker to dispatch outbox events."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sma.phase3_allocation.outbox import OutboxDispatcher, Publisher, SystemClock


logger = logging.getLogger("outbox_dispatcher")


class StdoutPublisher(Publisher):
    """Simple publisher that writes events to stdout."""

    def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
        message = {
            "event_type": event_type,
            "payload": payload,
            "headers": headers,
        }
        print(json.dumps(message, ensure_ascii=False))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatcher outbox")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "sqlite:///allocation.db"))
    parser.add_argument("--once", action="store_true", help="یکبار اجرا شود")
    parser.add_argument("--sleep", type=float, default=1.0, help="فاصله بررسی در حالت حلقه")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = create_engine(args.database_url, future=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = SessionFactory()
    try:
        dispatcher = OutboxDispatcher(
            session=session,
            publisher=StdoutPublisher(),
            clock=SystemClock(),
        )
        dispatcher.run_loop(once=args.once, sleep=args.sleep)
        return 0
    except Exception as exc:  # pragma: no cover - CLI guard
        logger.error("اجرای دیسپچر با خطا متوقف شد", extra={"کد": "DISPATCHER_ERROR", "جزئیات": str(exc)})
        print(f"DISPATCHER_ERROR|{exc}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
