from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class UploadModel(Base):
    __tablename__ = "uploads"

    id = Column(String(64), primary_key=True)
    profile = Column(String(32), nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    sha256 = Column(String(64))
    record_count = Column(Integer)
    size_bytes = Column(Integer)
    manifest_path = Column(String(255))
    source_filename = Column(String(255))
    namespace = Column(String(64), nullable=False, default="default")
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class ActiveRosterModel(Base):
    __tablename__ = "active_rosters"
    __table_args__ = (UniqueConstraint("year", name="uq_active_year"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    upload_id = Column(String(64), nullable=False)
    activated_at = Column(DateTime, nullable=False)


@dataclass(slots=True)
class UploadRecord:
    id: str
    profile: str
    year: int
    status: str
    sha256: Optional[str]
    record_count: Optional[int]
    size_bytes: Optional[int]
    manifest_path: Optional[str]
    source_filename: Optional[str]
    namespace: str
    created_at: datetime
    updated_at: datetime

    def manifest(self) -> Optional[dict]:
        if self.manifest_path:
            with open(self.manifest_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return None


class UploadRepository:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self.engine)

    def create_upload(
        self,
        *,
        profile: str,
        year: int,
        namespace: str,
        clock_now: datetime,
        source_filename: str,
    ) -> UploadRecord:
        upload_id = uuid4().hex
        with self.session_factory.begin() as session:
            model = UploadModel(
                id=upload_id,
                profile=profile,
                year=year,
                status="pending",
                namespace=namespace,
                created_at=clock_now,
                updated_at=clock_now,
                source_filename=source_filename,
            )
            session.add(model)
        return self.get(upload_id)

    def get(self, upload_id: str) -> UploadRecord:
        with self.session_factory() as session:
            model = session.get(UploadModel, upload_id)
            if not model:
                raise KeyError(upload_id)
            return self._to_record(model)

    def _to_record(self, model: UploadModel) -> UploadRecord:
        return UploadRecord(
            id=model.id,
            profile=model.profile,
            year=model.year,
            status=model.status,
            sha256=model.sha256,
            record_count=model.record_count,
            size_bytes=model.size_bytes,
            manifest_path=model.manifest_path,
            source_filename=model.source_filename,
            namespace=model.namespace,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def update_manifest(
        self,
        upload_id: str,
        *,
        sha256: str,
        record_count: int,
        size_bytes: int,
        manifest_path: str,
        clock_now: datetime,
    ) -> UploadRecord:
        with self.session_factory.begin() as session:
            model = session.get(UploadModel, upload_id, with_for_update=False)
            if not model:
                raise KeyError(upload_id)
            model.sha256 = sha256
            model.record_count = record_count
            model.size_bytes = size_bytes
            model.manifest_path = manifest_path
            model.status = "ready"
            model.updated_at = clock_now
        return self.get(upload_id)

    def activate(self, upload_id: str, *, clock_now: datetime) -> UploadRecord:
        with self.session_factory.begin() as session:
            upload = session.get(UploadModel, upload_id, with_for_update=False)
            if not upload:
                raise KeyError(upload_id)
            if upload.status != "ready":
                raise ValueError("upload not ready")
            try:
                session.add(
                    ActiveRosterModel(
                        year=upload.year,
                        upload_id=upload_id,
                        activated_at=clock_now,
                    )
                )
                session.flush()
            except IntegrityError as exc:
                raise exc
            upload.status = "active"
            upload.updated_at = clock_now
        return self.get(upload_id)


def create_sqlite_repository(path: str = ":memory:") -> UploadRepository:
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    repo = UploadRepository(engine)
    repo.create_schema()
    return repo
