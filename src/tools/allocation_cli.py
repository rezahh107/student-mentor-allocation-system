"""Command-line allocator for operators."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.phase3_allocation.allocation_tx import (
    AllocationRequest,
    AllocationResult,
    AllocationSequenceProvider,
    AtomicAllocator,
    PolicyEngine,
    PolicyVerdict,
    SimpleAllocationSequenceProvider,
)
from src.phase3_allocation.outbox import SystemClock
from src.phase3_allocation.uow import SQLAlchemyUnitOfWork


logger = logging.getLogger("allocation_cli")


@dataclass(slots=True)
class AlwaysApprovePolicy:
    """Minimal policy adapter approving all requests."""

    def evaluate(self, *, student, mentor, request: AllocationRequest) -> PolicyVerdict:  # type: ignore[override]
        return PolicyVerdict(approved=True, code="POLICY_OK", details={})


def build_allocator(database_url: str, sequence_provider: AllocationSequenceProvider | None = None) -> AtomicAllocator:
    engine = create_engine(database_url, future=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory=SessionFactory)

    clock = SystemClock()
    provider = sequence_provider or SimpleAllocationSequenceProvider(clock=clock)
    policy = AlwaysApprovePolicy()

    return AtomicAllocator(
        uow_factory=_uow_factory,
        sequence_provider=provider,
        policy_engine=policy,
        clock=clock,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ابزار تخصیص اتمیک")
    parser.add_argument("student_id", help="شناسه دانش‌آموز")
    parser.add_argument("mentor_id", help="شناسه منتور")
    parser.add_argument("--request-id", dest="request_id", help="شناسه درخواست")
    parser.add_argument("--payload", dest="payload", help="payload JSON", default="{}")
    parser.add_argument("--metadata", dest="metadata", help="metadata JSON", default="{}")
    parser.add_argument("--year-code", dest="year_code", help="کد سال")
    parser.add_argument("--database-url", dest="database_url", default=os.environ.get("DATABASE_URL", "sqlite:///allocation.db"))
    parser.add_argument("--dry-run", action="store_true", help="اجرای آزمایشی بدون ثبت")
    return parser.parse_args(argv)


def _load_json(value: str) -> dict:
    try:
        return json.loads(value) if value else {}
    except json.JSONDecodeError as exc:  # pragma: no cover - CLI guard
        raise SystemExit(f"PAYLOAD_INVALID_JSON|ساختار JSON نامعتبر است: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    allocator = build_allocator(args.database_url)
    payload = _load_json(args.payload)
    metadata = _load_json(args.metadata)

    request = AllocationRequest(
        studentId=args.student_id,
        mentorId=args.mentor_id,
        requestId=args.request_id,
        payload=payload,
        metadata=metadata,
        yearCode=args.year_code,
    )

    try:
        result: AllocationResult = allocator.allocate(request, dry_run=args.dry_run)
    except Exception as exc:  # pragma: no cover - CLI guard
        logger.error("اجرای تخصیص با خطا متوقف شد", extra={"کد": "CLI_ERROR", "جزئیات": str(exc)})
        print(f"CLI_ERROR|{exc}")
        return 1

    print(
        json.dumps(
            {
                "allocation_id": result.allocation_id,
                "allocation_code": result.allocation_code,
                "year_code": result.year_code,
                "mentor_id": result.mentor_id,
                "status": result.status,
                "message": result.message,
                "error_code": result.error_code,
                "idempotency_key": result.idempotency_key,
                "outbox_event_id": result.outbox_event_id,
                "dry_run": result.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
