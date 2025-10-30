from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from sma.phase6_import_to_sabt.app.utils import normalize_token
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _parse_center(value: str | None) -> int | None:
    normalized = normalize_token(value)
    if not normalized:
        return None
    if not normalized.isdigit():
        raise ValueError("center-format")
    number = int(normalized)
    if number <= 0:
        raise ValueError("center-range")
    return number


def build_router(workflow: ImportToSabtWorkflow) -> APIRouter:
    router = APIRouter()

    @router.post("/uploads")
    async def create_upload(
        request: Request,
        profile: str = Form(...),
        year: int = Form(...),
        file: UploadFile = File(...),  # noqa: B008
    ) -> dict[str, object]:
        temp_path = workflow.storage_dir / f"upload-{uuid.uuid4().hex}.tmp"
        with temp_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                handle.write(chunk)
        record = workflow.create_upload(profile=profile, year=year, file_path=temp_path)
        temp_path.unlink(missing_ok=True)
        return {
            "id": record.id,
            "status": record.status,
            "manifest": record.manifest,
        }

    @router.get("/uploads/{upload_id}")
    async def get_upload(upload_id: str) -> dict[str, object]:
        record = workflow.get_upload(upload_id)
        if record is None:
            raise HTTPException(status_code=404, detail="UPLOAD_NOT_FOUND")
        return {
            "id": record.id,
            "status": record.status,
            "manifest": record.manifest,
        }

    @router.post("/uploads/{upload_id}/activate")
    async def activate_upload(upload_id: str) -> dict[str, object]:
        try:
            record = workflow.activate_upload(upload_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="UPLOAD_NOT_FOUND") from exc
        return {
            "id": record.id,
            "status": record.status,
            "manifest": record.manifest,
        }

    @router.post("/exports")
    async def create_export(
        request: Request,
        year: int = Query(...),
        center: str | None = Query(default=None),
        format: str = Query(default="xlsx", alias="format"),
    ) -> dict[str, object]:
        try:
            center_value = _parse_center(center)
        except ValueError as exc:
            detail = {
                "code": "EXPORT_CENTER_INVALID",
                "message": "شناسهٔ مرکز نامعتبر است.",
            }
            raise HTTPException(status_code=400, detail=detail) from exc

        try:
            record = workflow.create_export(
                year=year,
                center=center_value,
                file_format=format,
            )
        except ValueError as exc:
            detail = {
                "code": "EXPORT_VALIDATION_ERROR",
                "message": str(exc),
            }
            raise HTTPException(status_code=400, detail=detail) from exc
        except RuntimeError as exc:
            detail = {
                "code": "EXPORT_IO_ERROR",
                "message": str(exc),
            }
            raise HTTPException(status_code=500, detail=detail) from exc
        return {
            "id": record.id,
            "status": record.status,
            "format": record.format,
            "manifest": record.manifest,
            "metadata": record.metadata,
        }

    @router.get("/exports/{export_id}")
    async def get_export(request: Request, export_id: str) -> dict[str, object]:
        record = workflow.get_export(export_id)
        if record is None:
            raise HTTPException(status_code=404, detail="EXPORT_NOT_FOUND")
        download_urls = workflow.build_signed_urls(record)
        return {
            "id": record.id,
            "status": record.status,
            "format": record.format,
            "files": record.files,
            "download_urls": download_urls,
            "manifest": record.manifest,
            "metadata": record.metadata,
        }

    return router


__all__ = ["build_router"]
