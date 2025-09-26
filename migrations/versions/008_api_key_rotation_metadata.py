"""add rotation metadata to api_keys"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "008_api_key_rotation_metadata"
down_revision = "007_seed_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("rotation_hint", sa.String(length=256), nullable=True, server_default=""))


def downgrade() -> None:
    op.drop_column("api_keys", "rotation_hint")
    op.drop_column("api_keys", "disabled_at")
