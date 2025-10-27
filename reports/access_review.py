"""Generate monthly access-review reports from audit events."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from dateutil import relativedelta

from sma.audit.repository import AuditQuery
from sma.audit.service import AuditEventRecord, AuditService


def _month_range(month: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(f"{month}-01T00:00:00+00:00")
    end = start + relativedelta.relativedelta(months=1)
    return start, end


async def generate_access_review(
    service: AuditService,
    *,
    output_dir: Path,
    month: str,
) -> Path:
    """Generate an access-review JSON report for the given month."""

    output_dir.mkdir(parents=True, exist_ok=True)
    start, end = _month_range(month)
    query = AuditQuery(from_ts=start, to_ts=end)
    events: list[AuditEventRecord] = []
    async for event in service.stream_events(query):
        events.append(event)

    summary = _summarize(events)
    payload = {
        "month": month,
        "from_ts": start.isoformat(),
        "to_ts": end.isoformat(),
        "total_events": len(events),
        "summary": summary,
    }
    path = output_dir / f"access_review_{month}.json"
    tmp_path = path.with_suffix(".json.part")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(path)
    return path


def _summarize(events: Iterable[AuditEventRecord]) -> dict[str, dict[str, int]]:
    by_role: defaultdict[str, int] = defaultdict(int)
    by_action: defaultdict[str, int] = defaultdict(int)
    by_outcome: defaultdict[str, int] = defaultdict(int)
    for event in events:
        by_role[event.actor_role.value] += 1
        by_action[event.action.value] += 1
        by_outcome[event.outcome.value] += 1
    return {
        "by_role": dict(sorted(by_role.items())),
        "by_action": dict(sorted(by_action.items())),
        "by_outcome": dict(sorted(by_outcome.items())),
    }


__all__ = ["generate_access_review"]

