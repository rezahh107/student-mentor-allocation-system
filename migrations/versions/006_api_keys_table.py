"""create api_keys table"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "006_api_keys_table"
down_revision = "005_allocation_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_active", "api_keys", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_active", table_name="api_keys")
    op.drop_table("api_keys")
