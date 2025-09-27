from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from .workflow import ImportToSabtWorkflow


def build_router(workflow: ImportToSabtWorkflow) -> APIRouter:
    router = APIRouter()

    @router.post("/uploads")
    async def create_upload(
        request: Request,
        profile: str = Form(...),
        year: int = Form(...),
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        temp_path = workflow.storage_dir / f"upload-{uuid.uuid4().hex}.tmp"
        with temp_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                handle.write(chunk)
        record = workflow.create_upload(profile=profile, year=year, file_path=temp_path)
        temp_path.unlink(missing_ok=True)
        chain = getattr(request.state, "middleware_chain", [])
        return {
            "id": record.id,
            "status": record.status,
            "manifest": record.manifest,
            "middleware_chain": chain,
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
        center: int | None = Query(default=None),
        format: str = Query(default="xlsx", alias="format"),
    ) -> dict[str, object]:
        try:
            record = workflow.create_export(year=year, center=center, file_format=format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "EXPORT_VALIDATION_ERROR", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail={"code": "EXPORT_IO_ERROR", "message": str(exc)}) from exc
        chain = getattr(request.state, "middleware_chain", [])
        return {
            "id": record.id,
            "status": record.status,
            "format": record.format,
            "manifest": record.manifest,
            "metadata": record.metadata,
            "middleware_chain": chain,
        }

    @router.get("/exports/{export_id}")
    async def get_export(export_id: str) -> dict[str, object]:
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
