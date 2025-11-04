# -*- coding: utf-8 -*-
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

from sma.core.datetime_utils import utc_now
from sma.audit.models import AuditEvent as _AuditEventTable


Base = declarative_base()


class StudentModel(Base):
    __tablename__ = "دانش_آموزان"

    national_id = Column("کد_ملی", String(10), primary_key=True)
    first_name = Column("نام", String, nullable=True)
    last_name = Column("نام_خانوادگی", String, nullable=True)
    father_name = Column("نام_پدر", String, nullable=True)
    birth_date = Column("تاریخ_تولد", Date, nullable=True)
    gender = Column("جنسیت", SmallInteger, nullable=False)
    edu_status = Column("وضعیت_تحصیلی", SmallInteger, nullable=False)  # 0=grad,1=student
    reg_center = Column("مرکز_ثبت_نام", SmallInteger, nullable=False)
    reg_status = Column("وضعیت_ثبت_نام", SmallInteger, nullable=False)
    group_code = Column("کد_گروه", Integer, nullable=False)
    school_code = Column("کد_مدرسه", Integer, nullable=True)
    student_type = Column("نوع_دانش_آموز", SmallInteger, nullable=True)
    mobile = Column("شماره_تلفن", String(11), nullable=True)
    counter = Column("شمارنده", String(9), unique=True)

    assignments = relationship("AssignmentModel", back_populates="student")

    __table_args__ = (
        CheckConstraint(
            '"وضعیت_ثبت_نام" IN (0, 1, 3)',
            name="ck_reg_status_domain",
        ),
        CheckConstraint(
            "\"شمارنده\" IS NULL OR ("
            "length(\"شمارنده\") = 9 AND "
            "\"شمارنده\" GLOB '[0-9]*' AND "
            "substr(\"شمارنده\", 3, 3) IN ('357','373')"
            ")",
            name="ck_counter_pattern",
        ),
        Index("ix_دانش_آموزان_کد_گروه", "کد_گروه"),
    )


class MentorModel(Base):
    __tablename__ = "منتورها"

    mentor_id = Column("شناسه_منتور", Integer, primary_key=True)
    name = Column("نام", String, nullable=True)
    gender = Column("جنسیت", SmallInteger, nullable=False)
    type = Column("نوع", Enum("عادی", "مدرسه", name="mentor_type", native_enum=False), nullable=False)
    capacity = Column("ظرفیت", Integer, nullable=False, default=60)
    current_load = Column("بار_فعلی", Integer, nullable=False, default=0)
    alias_code = Column("کد_مستعار", String, nullable=True)
    manager_id = Column(
        "شناسه_مدیر",
        Integer,
        ForeignKey("managers.manager_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column("فعال", Boolean, nullable=False, default=True)

    assignments = relationship("AssignmentModel", back_populates="mentor")
    manager = relationship("ManagerModel", back_populates="mentors")

    __table_args__ = (
        CheckConstraint("\"بار_فعلی\" >= 0"),
        CheckConstraint("\"ظرفیت\" >= 0"),
        Index("ix_منتورها_فیلتر", "جنسیت", "نوع", "فعال", "ظرفیت", "بار_فعلی"),
    )


class ManagerModel(Base):
    __tablename__ = "managers"

    manager_id = Column("manager_id", Integer, primary_key=True)
    full_name = Column("full_name", String(128), nullable=False)
    email = Column("email", String(254), nullable=True)
    phone = Column("phone", String(32), nullable=True)
    is_active = Column("is_active", Boolean, nullable=False, server_default="true")
    created_at = Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    mentors = relationship("MentorModel", back_populates="manager")
    allowed_centers = relationship(
        "ManagerAllowedCenterModel",
        back_populates="manager",
        cascade="all, delete-orphan",
        collection_class=set,
    )


class ManagerAllowedCenterModel(Base):
    __tablename__ = "manager_allowed_centers"

    manager_id = Column(
        "manager_id",
        Integer,
        ForeignKey("managers.manager_id", ondelete="CASCADE"),
        primary_key=True,
    )
    center_code = Column("center_code", SmallInteger, primary_key=True)

    manager = relationship("ManagerModel", back_populates="allowed_centers")

    __table_args__ = (Index("ix_mac_center", "center_code", "manager_id"),)


class AssignmentModel(Base):
    __tablename__ = "تخصیص_ها"

    assignment_id = Column("شناسه_تخصیص", BigInteger, primary_key=True, autoincrement=True)
    national_id = Column("کد_ملی", String(10), ForeignKey("دانش_آموزان.کد_ملی", ondelete="CASCADE"), nullable=False)
    mentor_id = Column("شناسه_منتور", Integer, ForeignKey("منتورها.شناسه_منتور"), nullable=True)
    assigned_at = Column("زمان_اختصاص", DateTime(timezone=True), nullable=False, default=utc_now)
    status = Column("وضعیت", Enum("OK", "TEMP_REVIEW", "NEEDS_NEW_MENTOR", name="alloc_status", native_enum=False), nullable=False)

    student = relationship("StudentModel", back_populates="assignments")
    mentor = relationship("MentorModel", back_populates="assignments")

    __table_args__ = (
        Index("ux_آخرین_تخصیص", "کد_ملی", "زمان_اختصاص"),
    )


class CounterSequenceModel(Base):
    __tablename__ = "شمارنده_ها"

    year_code = Column("کد_سال", CHAR(2), primary_key=True)
    gender_code = Column("کد_جنسیت", CHAR(3), primary_key=True)  # 357/373
    last_seq = Column("آخرین_عدد", Integer, nullable=False, default=0)


class AllocationRecord(Base):
    """Phase 3 atomic allocation rows with strict idempotency constraints."""

    __tablename__ = "allocations"

    allocation_id = Column(BigInteger, primary_key=True)
    allocation_code = Column(String(32), nullable=False, unique=True)
    year_code = Column(String(4), nullable=False)
    student_id = Column(String(32), ForeignKey("دانش_آموزان.کد_ملی"), nullable=False)
    mentor_id = Column(Integer, ForeignKey("منتورها.شناسه_منتور"), nullable=False)
    idempotency_key = Column(String(64), nullable=False, unique=True)
    request_id = Column(String(64), nullable=True)
    status = Column(
        Enum("CONFIRMED", "CANCELLED", name="allocation_status", native_enum=False),
        nullable=False,
        default="CONFIRMED",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    policy_code = Column(String(64), nullable=True)
    metadata_json = Column(Text, nullable=True)

    student = relationship("StudentModel")
    mentor = relationship("MentorModel")

    __table_args__ = (
        UniqueConstraint("student_id", "year_code", name="ux_alloc_student_year"),
    )


class OutboxMessageModel(Base):
    """Transport-agnostic outbox records for reliable dispatch."""

    __tablename__ = "outbox_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id = Column(String(36), nullable=False, unique=True)
    aggregate_type = Column(String(64), nullable=False)
    aggregate_id = Column(String(64), nullable=False)
    event_type = Column(String(96), nullable=False)
    payload_json = Column(Text, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    available_at = Column(DateTime(timezone=True), nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    status = Column(
        Enum("PENDING", "SENT", "FAILED", name="outbox_status", native_enum=False),
        nullable=False,
        default="PENDING",
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(256), nullable=True)

    __table_args__ = (
        CheckConstraint("length(payload_json) <= 32768", name="ck_outbox_payload_size"),
        CheckConstraint("retry_count >= 0", name="ck_outbox_retry_non_negative"),
        CheckConstraint(
            "status IN ('PENDING','SENT','FAILED')",
            name="ck_outbox_status_literal",
        ),
        Index("ix_outbox_dispatch", "status", "available_at"),
    )


class AuditEventModel(Base):
    """Re-export of the governance audit table for integration tests."""

    __table__ = _AuditEventTable.__table__

