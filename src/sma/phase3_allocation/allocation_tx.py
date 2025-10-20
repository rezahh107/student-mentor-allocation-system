"""Atomic allocation orchestration with idempotent outbox integration."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from sma.infrastructure.persistence.models import AllocationRecord, MentorModel, StudentModel

from .idempotency import derive_event_id, derive_idempotency_key, normalize_identifier
from .outbox import Clock, OutboxEvent, OutboxRepository
from .uow import UnitOfWorkFactory


logger = logging.getLogger(__name__)


class PolicyEngine(Protocol):
    """Policy contract for eligibility checks."""

    def evaluate(self, *, student: StudentModel, mentor: MentorModel, request: "AllocationRequest") -> "PolicyVerdict":
        """Return the policy decision."""


@dataclass(frozen=True)
class PolicyVerdict:
    """Policy decision container."""

    approved: bool
    code: str
    details: dict[str, Any]


@dataclass(frozen=True)
class AllocationIdentifiers:
    """Identifiers generated from sequence provider."""

    allocation_id: int
    year_code: str
    allocation_code: str


class AllocationSequenceProvider(Protocol):
    """Contract for allocation sequence provider."""

    def next(self, *, session: Session, student: StudentModel, mentor: MentorModel) -> AllocationIdentifiers:
        """Reserve a new allocation identifier."""


class AllocationRequest(BaseModel):
    """DTO carrying allocation inputs with backward compatible aliases."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    student_id: str = Field(validation_alias=AliasChoices("studentId", "student_id", "studentNationalId"))
    mentor_id: int = Field(validation_alias=AliasChoices("mentorId", "mentor_id"))
    request_id: str | None = Field(default=None, validation_alias=AliasChoices("requestId", "request_id"))
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    year_code: str | None = Field(default=None, alias="yearCode")

    @field_validator("student_id", mode="before")
    @classmethod
    def _normalize_student(cls, value: Any) -> str:
        return normalize_identifier(value)

    @field_validator("mentor_id", mode="before")
    @classmethod
    def _normalize_mentor(cls, value: Any) -> int:
        if value in (None, ""):
            return 0
        text = normalize_identifier(value)
        if not text:
            return 0
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("MENTOR_ID_INVALID|شناسه منتور نامعتبر است") from exc

    @field_validator("request_id", mode="before")
    @classmethod
    def _normalize_request(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = normalize_identifier(value)
        return text or None

    @field_validator("payload", "metadata", mode="before")
    @classmethod
    def _ensure_dict(cls, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("PAYLOAD_INVALID_JSON|ساختار JSON نامعتبر است") from exc
        if isinstance(value, dict):
            return value
        raise TypeError("PAYLOAD_NOT_MAPPING|ساختار ورودی باید دیکشنری باشد")


@dataclass(slots=True)
class AllocationResult:
    """Domain result of an allocation attempt."""

    allocation_id: int | None
    allocation_code: str | None
    year_code: str | None
    mentor_id: int | None
    status: str
    message: str
    error_code: str | None
    idempotency_key: str
    outbox_event_id: str | None
    dry_run: bool = False


class StudentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_update(self, student_id: str) -> StudentModel | None:
        stmt = (
            select(StudentModel)
            .where(StudentModel.national_id == student_id)
            .with_for_update()
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result


class MentorRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_update(self, mentor_id: int) -> MentorModel | None:
        stmt = select(MentorModel).where(MentorModel.mentor_id == mentor_id).with_for_update()
        return self._session.execute(stmt).scalar_one_or_none()


class AllocationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_idempotency_key(self, key: str) -> AllocationRecord | None:
        stmt = select(AllocationRecord).where(AllocationRecord.idempotency_key == key)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_student_year(self, student_id: str, year_code: str) -> AllocationRecord | None:
        stmt = select(AllocationRecord).where(
            AllocationRecord.student_id == student_id,
            AllocationRecord.year_code == year_code,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, record: AllocationRecord) -> None:
        self._session.add(record)


@dataclass(slots=True)
class SimpleAllocationSequenceProvider(AllocationSequenceProvider):
    """Sequence provider compatible with legacy allocation codes."""

    clock: Clock
    legacy_width: int = 8

    def next(self, *, session: Session, student: StudentModel, mentor: MentorModel) -> AllocationIdentifiers:
        now_year = self.clock.now().year
        year_code = f"{now_year % 100:02d}"
        max_id = session.execute(select(func.max(AllocationRecord.allocation_id))).scalar()
        next_id = (max_id or 0) + 1
        allocation_code = f"{year_code}{next_id:0{self.legacy_width}d}"
        return AllocationIdentifiers(
            allocation_id=next_id,
            year_code=year_code,
            allocation_code=allocation_code,
        )


class AtomicAllocator:
    """Co-ordinates allocation workflow inside retries and transactions."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        sequence_provider: AllocationSequenceProvider,
        policy_engine: PolicyEngine,
        clock: Clock,
        max_retries: int = 3,
    ) -> None:
        self._uow_factory = uow_factory
        self._sequence_provider = sequence_provider
        self._policy_engine = policy_engine
        self._clock = clock
        self._max_retries = max_retries

    def allocate(self, request: AllocationRequest, *, dry_run: bool = False) -> AllocationResult:
        attempt = 0
        while True:
            try:
                return self._execute_once(request=request, dry_run=dry_run)
            except OperationalError as exc:
                attempt += 1
                if attempt > self._max_retries:
                    logger.error(
                        "تخصیص به دلیل خطای تراکنش شکست خورد",
                        extra={"کد": "TX_FAILED", "detail": str(exc)},
                    )
                    raise
                backoff = min(0.5 * (2 ** attempt), 5.0)
                logger.warning(
                    "تراکنش با خطای رقابت مواجه شد؛ تلاش مجدد",
                    extra={"کد": "TX_RETRY", "تاخیر": backoff, "تلاش": attempt},
                )
                time.sleep(backoff)

    def _execute_once(self, *, request: AllocationRequest, dry_run: bool) -> AllocationResult:
        idempotency_key = derive_idempotency_key(
            student_id=request.student_id,
            mentor_id=request.mentor_id,
            request_id=request.request_id,
            payload=request.payload,
        )

        with self._uow_factory() as uow:
            student_repo = StudentRepository(uow.session)
            mentor_repo = MentorRepository(uow.session)
            allocation_repo = AllocationRepository(uow.session)
            outbox_repo = OutboxRepository(uow.session)

            existing = allocation_repo.get_by_idempotency_key(idempotency_key)
            if existing:
                event_id = str(derive_event_id(idempotency_key))
                return AllocationResult(
                    allocation_id=existing.allocation_id,
                    allocation_code=existing.allocation_code,
                    year_code=existing.year_code,
                    mentor_id=existing.mentor_id,
                    status="ALREADY_ASSIGNED",
                    message="درخواست قبلی با موفقیت ثبت شده است",
                    error_code="ALREADY_ASSIGNED",
                    idempotency_key=idempotency_key,
                    outbox_event_id=event_id,
                )

            mentor = mentor_repo.get_for_update(request.mentor_id)
            if mentor is None:
                return AllocationResult(
                    allocation_id=None,
                    allocation_code=None,
                    year_code=None,
                    mentor_id=None,
                    status="MENTOR_NOT_FOUND",
                    message="منتور یافت نشد",
                    error_code="MENTOR_NOT_FOUND",
                    idempotency_key=idempotency_key,
                    outbox_event_id=None,
                )

            student = student_repo.get_for_update(request.student_id)
            if student is None:
                return AllocationResult(
                    allocation_id=None,
                    allocation_code=None,
                    year_code=None,
                    mentor_id=None,
                    status="STUDENT_NOT_FOUND",
                    message="دانش‌آموز یافت نشد",
                    error_code="STUDENT_NOT_FOUND",
                    idempotency_key=idempotency_key,
                    outbox_event_id=None,
                )

            verdict = self._policy_engine.evaluate(student=student, mentor=mentor, request=request)
            if not verdict.approved:
                return AllocationResult(
                    allocation_id=None,
                    allocation_code=None,
                    year_code=None,
                    mentor_id=None,
                    status="POLICY_REJECT",
                    message="درخواست توسط سیاست رد شد",
                    error_code=verdict.code or "POLICY_REJECT",
                    idempotency_key=idempotency_key,
                    outbox_event_id=None,
                )

            if dry_run:
                logger.info(
                    "اجرای آزمایشی تخصیص بدون ثبت",
                    extra={"کد": "DRY_RUN", "student": student.national_id, "mentor": mentor.mentor_id},
                )
                return AllocationResult(
                    allocation_id=None,
                    allocation_code=None,
                    year_code=request.year_code,
                    mentor_id=mentor.mentor_id,
                    status="DRY_RUN",
                    message="اجرای آزمایشی بدون ثبت",
                    error_code=None,
                    idempotency_key=idempotency_key,
                    outbox_event_id=None,
                    dry_run=True,
                )

            identifiers = self._sequence_provider.next(session=uow.session, student=student, mentor=mentor)

            if request.year_code and request.year_code != identifiers.year_code:
                logger.warning(
                    "کد سال در درخواست با شمارنده مغایرت دارد",
                    extra={"کد": "YEAR_MISMATCH", "درخواست": request.year_code, "سیستم": identifiers.year_code},
                )

            record = AllocationRecord(
                allocation_id=identifiers.allocation_id,
                allocation_code=identifiers.allocation_code,
                year_code=identifiers.year_code,
                student_id=student.national_id,
                mentor_id=mentor.mentor_id,
                idempotency_key=idempotency_key,
                request_id=request.request_id,
                status="CONFIRMED",
                metadata_json=json.dumps(request.metadata, ensure_ascii=False) if request.metadata else None,
                policy_code=verdict.code,
            )

            try:
                allocation_repo.add(record)
                now = self._clock.now()
                event_id = str(derive_event_id(idempotency_key))
                event = OutboxEvent(
                    event_id=event_id,
                    aggregate_type="Allocation",
                    aggregate_id=str(record.allocation_id),
                    event_type="MentorAssigned",
                    payload={
                        "event_id": event_id,
                        "allocation_id": record.allocation_id,
                        "allocation_code": record.allocation_code,
                        "year_code": record.year_code,
                        "student_id": record.student_id,
                        "mentor_id": record.mentor_id,
                        "idempotency_key": idempotency_key,
                        "status": record.status,
                        "occurred_at": now.isoformat(),
                    },
                    occurred_at=now,
                    available_at=now,
                )
                outbox_repo.add(event)
                uow.session.flush()
            except IntegrityError:
                uow.rollback()
                existing = allocation_repo.get_by_idempotency_key(idempotency_key)
                if existing is None and identifiers.year_code:
                    existing = allocation_repo.get_by_student_year(student.national_id, identifiers.year_code)
                if existing:
                    event_id = str(derive_event_id(idempotency_key))
                    return AllocationResult(
                        allocation_id=existing.allocation_id,
                        allocation_code=existing.allocation_code,
                        year_code=existing.year_code,
                        mentor_id=existing.mentor_id,
                        status="ALREADY_ASSIGNED",
                        message="درخواست تکراری تشخیص داده شد",
                        error_code="ALREADY_ASSIGNED",
                        idempotency_key=idempotency_key,
                        outbox_event_id=event_id,
                    )
                raise

            logger.info(
                "تخصیص با موفقیت ثبت شد",
                extra={
                    "کد": "ALLOCATED",
                    "student": student.national_id,
                    "mentor": mentor.mentor_id,
                    "allocation_id": identifiers.allocation_id,
                },
            )

            return AllocationResult(
                allocation_id=identifiers.allocation_id,
                allocation_code=identifiers.allocation_code,
                year_code=identifiers.year_code,
                mentor_id=mentor.mentor_id,
                status="OK",
                message="تخصیص با موفقیت انجام شد",
                error_code=None,
                idempotency_key=idempotency_key,
                outbox_event_id=str(derive_event_id(idempotency_key)),
            )
