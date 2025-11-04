"""Optional test data seeding (guarded by env RUN_TEST_SEED=1)

Revision ID: 004_test_data_seeding
Revises: 003_audit_triggers
Create Date: 2025-09-18 00:15:00.000000
"""
from __future__ import annotations

import os
from alembic import op


revision = "004_test_data_seeding"
down_revision = "003_audit_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if os.environ.get("RUN_TEST_SEED") != "1":
        return
    # Seed a small dataset for local performance tests
    op.execute(
        "INSERT INTO managers (manager_id, full_name, is_active) "
        "VALUES (1,'مدیر پیش‌فرض',true) ON CONFLICT (manager_id) DO NOTHING;"
    )
    op.execute(
        'INSERT INTO "منتورها" ("شناسه_منتور","نام","جنسیت","نوع","ظرفیت","بار_فعلی","شناسه_مدیر","فعال") '
        "VALUES (1,'A',0,'عادی',60,0,1,true) ON CONFLICT DO NOTHING;"
    )
    op.execute(
        'INSERT INTO "منتورها" ("شناسه_منتور","نام","جنسیت","نوع","ظرفیت","بار_فعلی","شناسه_مدیر","فعال") '
        "VALUES (2,'B',1,'مدرسه',60,0,1,true) ON CONFLICT DO NOTHING;"
    )
    op.execute("INSERT INTO mentor_allowed_groups(mentor_id, group_code) VALUES (1,101) ON CONFLICT DO NOTHING;")
    op.execute("INSERT INTO manager_allowed_centers(manager_id, center_code) VALUES (1,0) ON CONFLICT DO NOTHING;")
    op.execute("INSERT INTO mentor_schools(mentor_id, school_code) VALUES (2,123) ON CONFLICT DO NOTHING;")


def downgrade() -> None:
    if os.environ.get("RUN_TEST_SEED") != "1":
        return
    op.execute('DELETE FROM "دانش_آموزان";')
    op.execute('DELETE FROM mentor_allowed_groups;')
    op.execute('DELETE FROM manager_allowed_centers;')
    op.execute('DELETE FROM mentor_schools;')
    op.execute('DELETE FROM "منتورها";')
    op.execute('DELETE FROM managers;')

