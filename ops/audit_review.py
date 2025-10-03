"""Generate access review reports for the last 30 days."""
from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine

from src.audit.exporter import _atomic_async_write  # type: ignore
from src.audit.release_manifest import ReleaseManifest, make_manifest_entry
from src.audit.repository import AuditQuery, AuditRepository
from src.audit.service import AuditService, build_metrics
from src.phase7_release.hashing import sha256_file
from src.reliability.clock import Clock

REPORTS_DIR = Path("reports")
DEFAULT_DSN = "sqlite:///reports/audit.db"


async def generate_access_review(
    *,
    service: AuditService,
    manifest: ReleaseManifest,
) -> tuple[Path, Path]:
    now = service.now()
    start = now - timedelta(days=30)
    query = AuditQuery(from_ts=start, to_ts=now, limit=None, offset=0)
    summary = defaultdict(int)
    async for event in service.stream_events(query):
        key = (
            event.actor_role.value,
            event.center_scope or "",
            event.action.value,
            event.outcome.value,
        )
        summary[key] += 1
    rows = [
        {
            "actor_role": role,
            "center_scope": center,
            "action": action,
            "outcome": outcome,
            "count": count,
        }
        for (role, center, action, outcome), count in sorted(summary.items())
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / f"audit_review_{now.strftime('%Y%m%d')}.csv"
    json_path = REPORTS_DIR / f"audit_review_{now.strftime('%Y%m%d')}.json"

    async def write_csv(handle):
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(["actor_role", "center_scope", "action", "outcome", "count"])
        for row in rows:
            writer.writerow([row["actor_role"], row["center_scope"], row["action"], row["outcome"], str(row["count"])])

    async def write_json(handle):
        data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        handle.write(data)

    await _atomic_async_write(csv_path, write_csv)
    await _atomic_async_write(json_path, write_json)

    csv_digest = sha256_file(csv_path)
    json_digest = sha256_file(json_path)
    manifest.update(entry=make_manifest_entry(csv_path, sha256=csv_digest, kind="audit-review-csv", ts=now))
    manifest.update(entry=make_manifest_entry(json_path, sha256=json_digest, kind="audit-review-json", ts=now))
    service.record_review_run("ok")
    return csv_path, json_path


async def _build_service(dsn: str) -> tuple[AuditService, ReleaseManifest]:
    engine = create_engine(dsn, future=True)
    repository = AuditRepository(engine)
    await repository.init()
    clock = Clock(timezone=service_tz())
    metrics = build_metrics()
    service = AuditService(repository, clock, metrics=metrics)
    manifest = ReleaseManifest(Path("release.json"))
    return service, manifest


def service_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Tehran")


async def _main(dsn: str = DEFAULT_DSN) -> None:
    service, manifest = await _build_service(dsn)
    await generate_access_review(service=service, manifest=manifest)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
