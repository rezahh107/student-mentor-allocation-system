"""Phase 3 allocation + outbox tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "005_allocation_outbox"
down_revision = "004_test_data_seeding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allocations",
        sa.Column("allocation_id", sa.BigInteger(), primary_key=True),
        sa.Column("allocation_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("year_code", sa.String(length=4), nullable=False),
        sa.Column("student_id", sa.String(length=32), nullable=False),
        sa.Column("mentor_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("CONFIRMED", "CANCELLED", name="allocation_status", native_enum=False),
            nullable=False,
            server_default="CONFIRMED",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("policy_code", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["دانش_آموزان.کد_ملی"]),
        sa.ForeignKeyConstraint(["mentor_id"], ["منتورها.شناسه_منتور"]),
        sa.UniqueConstraint("student_id", "year_code", name="ux_alloc_student_year"),
    )

    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SENT", "FAILED", name="outbox_status", native_enum=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=256), nullable=True),
        sa.CheckConstraint("length(payload_json) <= 32768", name="ck_outbox_payload_size"),
        sa.CheckConstraint("retry_count >= 0", name="ck_outbox_retry_non_negative"),
        sa.CheckConstraint(
            "status IN ('PENDING','SENT','FAILED')",
            name="ck_outbox_status_literal",
        ),
    )

    op.create_index(
        "ix_outbox_dispatch",
        "outbox_messages",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_dispatch", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_table("allocations")

    op.execute("DROP TYPE IF EXISTS allocation_status")
    op.execute("DROP TYPE IF EXISTS outbox_status")
