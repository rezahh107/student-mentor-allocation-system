"""Create monthly indexes for audit events to emulate partitioning."""
from __future__ import annotations

from datetime import datetime

from alembic import op
from zoneinfo import ZoneInfo

from sma.audit.partitioning import ensure_monthly_partition_indexes


revision = "006_audit_monthly_partitions"
down_revision = "005_allocation_outbox"
branch_labels = None
depends_on = None

_TZ = ZoneInfo("Asia/Tehran")


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(tz=_TZ)
    start = now.replace(year=now.year - 2, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(month=now.month, day=1, hour=0, minute=0, second=0, microsecond=0)
    ensure_monthly_partition_indexes(bind, start=start, end=end)


def downgrade() -> None:
    bind = op.get_bind()
    with bind.begin() as connection:
        rows = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE 'ix_audit_events_month_%'
            """
        )
        names = [row[0] for row in rows]
        for name in names:
            connection.execute(f"DROP INDEX IF EXISTS {name}")
