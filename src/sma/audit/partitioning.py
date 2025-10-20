"""Partition management helpers for the audit_events table."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Tehran")


@dataclass(slots=True)
class PartitionPlan:
    month_key: str
    start: datetime
    end: datetime


def month_key(dt: datetime, *, tz: ZoneInfo = _TZ) -> str:
    localized = dt.astimezone(tz)
    return f"{localized.year:04d}_{localized.month:02d}"


def iter_months(start: datetime, end: datetime, *, tz: ZoneInfo = _TZ) -> Iterable[PartitionPlan]:
    current = start.astimezone(tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    limit = end.astimezone(tz)
    while current < limit:
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1)
        else:
            next_month = current.replace(month=current.month + 1)
        yield PartitionPlan(
            month_key=f"{current.year:04d}_{current.month:02d}",
            start=current,
            end=next_month,
        )
        current = next_month


def ensure_monthly_partition_indexes(engine: Engine | Connection, *, start: datetime, end: datetime) -> list[str]:
    """Create partial indexes per month to emulate partitioning under SQLite tests."""

    plans = list(iter_months(start, end))
    created: list[str] = []
    if isinstance(engine, Connection):
        connection = engine
        should_close = False
    else:
        connection = engine.connect()
        should_close = True
    transaction = connection.begin()
    try:
        dialect = connection.dialect.name
        for plan in plans:
            idx_name = f"ix_audit_events_month_{plan.month_key}"
            if dialect == "sqlite":
                start_literal = plan.start.isoformat()
                end_literal = plan.end.isoformat()
                stmt = text(
                    f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON audit_events(ts)
                    WHERE ts >= '{start_literal}' AND ts < '{end_literal}'
                    """
                )
                connection.execute(stmt)
                created.append(idx_name)
                continue
            else:
                stmt = text(
                    f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON audit_events(ts)
                    WHERE ts >= :start AND ts < :end
                    """
                )
            connection.execute(stmt, {"start": plan.start, "end": plan.end})
            created.append(idx_name)
    finally:
        transaction.commit()
        if should_close:
            connection.close()
    return created


__all__ = ["ensure_monthly_partition_indexes", "PartitionPlan", "iter_months", "month_key"]
