# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class StudentModel(Base):
    __tablename__ = "دانش_آموزان"

    national_id = Column("کد_ملی", String(10), primary_key=True)
    first_name = Column("نام", String, nullable=True)
    last_name = Column("نام_خانوادگی", String, nullable=True)
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
    manager_id = Column("شناسه_مدیر", Integer, nullable=True)
    is_active = Column("فعال", Boolean, nullable=False, default=True)

    assignments = relationship("AssignmentModel", back_populates="mentor")

    __table_args__ = (
        CheckConstraint("\"بار_فعلی\" >= 0"),
        CheckConstraint("\"ظرفیت\" >= 0"),
        Index("ix_منتورها_فیلتر", "جنسیت", "نوع", "فعال", "ظرفیت", "بار_فعلی"),
    )


class AssignmentModel(Base):
    __tablename__ = "تخصیص_ها"

    assignment_id = Column("شناسه_تخصیص", BigInteger, primary_key=True, autoincrement=True)
    national_id = Column("کد_ملی", String(10), ForeignKey("دانش_آموزان.کد_ملی", ondelete="CASCADE"), nullable=False)
    mentor_id = Column("شناسه_منتور", Integer, ForeignKey("منتورها.شناسه_منتور"), nullable=True)
    assigned_at = Column("زمان_اختصاص", DateTime(timezone=True), nullable=False, default=datetime.utcnow)
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

