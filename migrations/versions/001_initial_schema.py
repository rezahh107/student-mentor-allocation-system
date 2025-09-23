"""Initial schema with Persian tables and link tables

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-09-18 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Students
    op.create_table(
        "دانش_آموزان",
        sa.Column("کد_ملی", sa.String(10), primary_key=True),
        sa.Column("نام", sa.String(), nullable=True),
        sa.Column("نام_خانوادگی", sa.String(), nullable=True),
        sa.Column("جنسیت", sa.SmallInteger(), nullable=False),
        sa.Column("وضعیت_تحصیلی", sa.SmallInteger(), nullable=False),
        sa.Column("مرکز_ثبت_نام", sa.SmallInteger(), nullable=False),
        sa.Column("وضعیت_ثبت_نام", sa.SmallInteger(), nullable=False),
        sa.Column("کد_گروه", sa.Integer(), nullable=False),
        sa.Column("کد_مدرسه", sa.Integer(), nullable=True),
        sa.Column("نوع_دانش_آموز", sa.SmallInteger(), nullable=True),
        sa.Column("شماره_تلفن", sa.String(11), nullable=True),
        sa.Column("شمارنده", sa.String(9), nullable=True, unique=True),
    )
    op.create_index("ix_دانش_آموزان_کد_گروه", "دانش_آموزان", ["کد_گروه"])

    # Mentors
    mentor_type = sa.Enum("عادی", "مدرسه", name="mentor_type", native_enum=False)
    mentor_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "منتورها",
        sa.Column("شناسه_منتور", sa.Integer(), primary_key=True),
        sa.Column("نام", sa.String(), nullable=True),
        sa.Column("جنسیت", sa.SmallInteger(), nullable=False),
        sa.Column("نوع", mentor_type, nullable=False),
        sa.Column("ظرفیت", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("بار_فعلی", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("کد_مستعار", sa.String(), nullable=True),
        sa.Column("شناسه_مدیر", sa.Integer(), nullable=True),
        sa.Column("فعال", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint('"بار_فعلی" >= 0'),
        sa.CheckConstraint('"ظرفیت" >= 0'),
    )
    op.create_index("ix_منتورها_فیلتر", "منتورها", ["جنسیت", "نوع", "فعال", "ظرفیت", "بار_فعلی"])  # order matches filters

    # Assignments
    alloc_status = sa.Enum("OK", "TEMP_REVIEW", "NEEDS_NEW_MENTOR", name="alloc_status", native_enum=False)
    alloc_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "تخصیص_ها",
        sa.Column("شناسه_تخصیص", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("کد_ملی", sa.String(10), sa.ForeignKey("دانش_آموزان.کد_ملی", ondelete="CASCADE"), nullable=False),
        sa.Column("شناسه_منتور", sa.Integer(), sa.ForeignKey("منتورها.شناسه_منتور"), nullable=True),
        sa.Column("زمان_اختصاص", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("وضعیت", alloc_status, nullable=False),
    )
    op.create_index("ux_آخرین_تخصیص", "تخصیص_ها", ["کد_ملی", "زمان_اختصاص"])

    # Counter sequences
    op.create_table(
        "شمارنده_ها",
        sa.Column("کد_سال", sa.CHAR(2), primary_key=True),
        sa.Column("کد_جنسیت", sa.CHAR(3), primary_key=True),
        sa.Column("آخرین_عدد", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # Link tables (English names per existing code)
    op.create_table(
        "mentor_allowed_groups",
        sa.Column("mentor_id", sa.Integer(), sa.ForeignKey("منتورها.شناسه_منتور", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_code", sa.Integer(), primary_key=True),
    )
    op.create_table(
        "manager_allowed_centers",
        sa.Column("manager_id", sa.Integer(), primary_key=True),
        sa.Column("center_code", sa.SmallInteger(), primary_key=True),
    )
    op.create_table(
        "mentor_schools",
        sa.Column("mentor_id", sa.Integer(), sa.ForeignKey("منتورها.شناسه_منتور", ondelete="CASCADE"), primary_key=True),
        sa.Column("school_code", sa.Integer(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("mentor_schools")
    op.drop_table("manager_allowed_centers")
    op.drop_table("mentor_allowed_groups")
    op.drop_table("شمارنده_ها")
    op.drop_index("ux_آخرین_تخصیص", table_name="تخصیص_ها")
    op.drop_table("تخصیص_ها")
    op.drop_index("ix_منتورها_فیلتر", table_name="منتورها")
    op.drop_table("منتورها")
    op.drop_index("ix_دانش_آموزان_کد_گروه", table_name="دانش_آموزان")
    op.drop_table("دانش_آموزان")

