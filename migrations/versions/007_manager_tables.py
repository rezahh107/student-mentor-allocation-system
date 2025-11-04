"""Add manager table and link manager centers.

Revision ID: 007_manager_tables
Revises: 006_audit_monthly_partitions
Create Date: 2025-09-18 00:30:00.000000
"""
from __future__ import annotations

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa


revision = "007_manager_tables"
down_revision = "006_audit_monthly_partitions"
branch_labels = None
depends_on = None


def _iter_existing_manager_ids(bind) -> Iterable[int]:
    mentor_rows = bind.execute(
        sa.text('SELECT DISTINCT "شناسه_مدیر" FROM "منتورها" WHERE "شناسه_مدیر" IS NOT NULL')
    )
    for row in mentor_rows:
        value = row[0]
        if value is not None:
            yield int(value)
    center_rows = bind.execute(
        sa.text("SELECT DISTINCT manager_id FROM manager_allowed_centers")
    )
    for row in center_rows:
        value = row[0]
        if value is not None:
            yield int(value)


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

    bind = op.get_bind()
    dialect_name = bind.dialect.name
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
    op.drop_constraint("fk_manager_centers_manager", "manager_allowed_centers", type_="foreignkey")
    op.drop_constraint("fk_mentors_manager", "منتورها", type_="foreignkey")
    op.drop_index("ix_managers_active_name", table_name="managers")
    op.drop_table("managers")
