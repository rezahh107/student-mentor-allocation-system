"""Performance indexes and partials

Revision ID: 002_performance_indexes
Revises: 001_initial_schema
Create Date: 2025-09-18 00:05:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "002_performance_indexes"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial index for available capacity
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_mentors_capacity_available ON "منتورها" ("جنسیت", "نوع", "فعال", "بار_فعلی", "ظرفیت") WHERE "بار_فعلی" < "ظرفیت";'
    )

    # Secondary indexes for link tables
    op.create_index("ix_mag_group", "mentor_allowed_groups", ["group_code", "mentor_id"], unique=False)
    op.create_index("ix_mac_center", "manager_allowed_centers", ["center_code", "manager_id"], unique=False)
    op.create_index("ix_ms_school", "mentor_schools", ["school_code", "mentor_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ms_school", table_name="mentor_schools")
    op.drop_index("ix_mac_center", table_name="manager_allowed_centers")
    op.drop_index("ix_mag_group", table_name="mentor_allowed_groups")
    op.execute('DROP INDEX IF EXISTS ix_mentors_capacity_available;')

