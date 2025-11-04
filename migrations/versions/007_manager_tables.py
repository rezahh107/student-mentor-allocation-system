"""Add manager table and link manager centers.

Revision ID: 007_manager_tables
Revises: 006_audit_monthly_partitions
Create Date: 2025-09-18 00:30:00.000000
"""
from __future__ import annotations

import os
from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa


revision = "007_manager_tables"
down_revision = "006_audit_monthly_partitions"
branch_labels = None
depends_on = None


def _iter_existing_manager_ids(bind) -> Iterable[int]:
    query = sa.text(
        'SELECT "شناسه_مدیر" FROM "منتورها" WHERE "شناسه_مدیر" IS NOT NULL '
        "UNION "
        "SELECT manager_id FROM manager_allowed_centers WHERE manager_id IS NOT NULL"
    )
    rows = bind.execute(query)
    for row in rows:
        yield int(row[0])


def _seed_test_manager_data(bind, dialect_name: str) -> None:
    if os.environ.get("RUN_TEST_SEED") != "1":
        return

    if dialect_name == "sqlite":
        manager_stmt = sa.text(
            "INSERT OR IGNORE INTO managers (manager_id, full_name, is_active) "
            "VALUES (1, 'مدیر پیش‌فرض', 1)"
        )
        centers_stmt = sa.text(
            "INSERT OR IGNORE INTO manager_allowed_centers (manager_id, center_code) "
            "VALUES (1, 0)"
        )
    else:
        manager_stmt = sa.text(
            "INSERT INTO managers (manager_id, full_name, is_active) "
            "VALUES (1, 'مدیر پیش‌فرض', true) "
            "ON CONFLICT (manager_id) DO NOTHING"
        )
        centers_stmt = sa.text(
            "INSERT INTO manager_allowed_centers (manager_id, center_code) "
            "VALUES (1, 0) ON CONFLICT DO NOTHING"
        )

    bind.execute(manager_stmt)
    bind.execute(centers_stmt)


def upgrade() -> None:
    op.create_table(
        "managers",
        sa.Column("manager_id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_managers_active_name",
        "managers",
        ["is_active", "full_name"],
    )
    op.create_index(
        "ix_mac_center",
        "manager_allowed_centers",
        ["center_code", "manager_id"],
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_mac_indexes = {index["name"] for index in inspector.get_indexes("manager_allowed_centers")}
    if "ix_mac_center" not in existing_mac_indexes:
        op.create_index(
            "ix_mac_center",
            "manager_allowed_centers",
            ["center_code", "manager_id"],
        )

    dialect_name = bind.dialect.name
    _seed_test_manager_data(bind, dialect_name)
    manager_ids = sorted(set(_iter_existing_manager_ids(bind)))
    if manager_ids:
        if dialect_name == "sqlite":
            insert_stmt = sa.text(
                "INSERT OR IGNORE INTO managers (manager_id, full_name, is_active) "
                "VALUES (:manager_id, :full_name, 1)"
            )
        else:
            insert_stmt = sa.text(
                "INSERT INTO managers (manager_id, full_name, is_active) "
                "VALUES (:manager_id, :full_name, true) "
                "ON CONFLICT (manager_id) DO NOTHING"
            )
        for manager_id in manager_ids:
            bind.execute(
                insert_stmt,
                {
                    "manager_id": manager_id,
                    "full_name": f"مدیر {manager_id}",
                },
            )

    op.create_foreign_key(
        "fk_mentors_manager",
        "منتورها",
        "managers",
        ["شناسه_مدیر"],
        ["manager_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_manager_centers_manager",
        "manager_allowed_centers",
        "managers",
        ["manager_id"],
        ["manager_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_mac_indexes = {index["name"] for index in inspector.get_indexes("manager_allowed_centers")}
    if "ix_mac_center" in existing_mac_indexes:
        op.drop_index("ix_mac_center", table_name="manager_allowed_centers")
    op.drop_constraint("fk_manager_centers_manager", "manager_allowed_centers", type_="foreignkey")
    op.drop_constraint("fk_mentors_manager", "منتورها", type_="foreignkey")
    op.drop_index("ix_mac_center", table_name="manager_allowed_centers")
    op.drop_index("ix_managers_active_name", table_name="managers")
    op.drop_table("managers")
