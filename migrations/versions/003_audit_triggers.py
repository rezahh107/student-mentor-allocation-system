"""Audit triggers for assignments and mentors

Revision ID: 003_audit_triggers
Revises: 002_performance_indexes
Create Date: 2025-09-18 00:10:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "003_audit_triggers"
down_revision = "002_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Audit table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
          audit_id BIGSERIAL PRIMARY KEY,
          table_name TEXT NOT NULL,
          operation TEXT NOT NULL,
          row_id TEXT,
          changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          before_data JSONB,
          after_data JSONB
        );
        """
    )

    # Audit function
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_row_change() RETURNS TRIGGER AS $$
        BEGIN
          IF (TG_OP = 'INSERT') THEN
            INSERT INTO audit_log(table_name, operation, row_id, after_data)
            VALUES (TG_TABLE_NAME, TG_OP, NEW::text, to_jsonb(NEW));
            RETURN NEW;
          ELSIF (TG_OP = 'UPDATE') THEN
            INSERT INTO audit_log(table_name, operation, row_id, before_data, after_data)
            VALUES (TG_TABLE_NAME, TG_OP, NEW::text, to_jsonb(OLD), to_jsonb(NEW));
            RETURN NEW;
          ELSIF (TG_OP = 'DELETE') THEN
            INSERT INTO audit_log(table_name, operation, row_id, before_data)
            VALUES (TG_TABLE_NAME, TG_OP, OLD::text, to_jsonb(OLD));
            RETURN OLD;
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Triggers
    op.execute(
        'CREATE TRIGGER trg_audit_assignments AFTER INSERT OR UPDATE OR DELETE ON "تخصیص_ها" FOR EACH ROW EXECUTE FUNCTION audit_row_change();'
    )
    op.execute(
        'CREATE TRIGGER trg_audit_mentors AFTER INSERT OR UPDATE OR DELETE ON "منتورها" FOR EACH ROW EXECUTE FUNCTION audit_row_change();'
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_audit_mentors ON "منتورها";')
    op.execute('DROP TRIGGER IF EXISTS trg_audit_assignments ON "تخصیص_ها";')
    op.execute('DROP FUNCTION IF EXISTS audit_row_change;')
    op.execute('DROP TABLE IF EXISTS audit_log;')

