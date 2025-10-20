from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow
from sma.phase6_import_to_sabt.app.utils import normalize_token
from sma.phase6_import_to_sabt.security.rbac import AuthorizationError, enforce_center_scope


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
        center: str | None = Query(default=None),
        format: str = Query(default="xlsx", alias="format"),
    ) -> dict[str, object]:
        try:
            center_value = _parse_center(center)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "EXPORT_CENTER_INVALID", "message": "شناسهٔ مرکز نامعتبر است."},
            ) from exc

        actor = getattr(request.state, "actor", None)
        if actor is None:
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "توکن نامعتبر است."})
        if actor.role == "MANAGER" and center_value is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "EXPORT_FORBIDDEN", "message": "دسترسی شما برای این مرکز مجاز نیست."},
            )
        try:
            enforce_center_scope(actor, center=center_value)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "EXPORT_FORBIDDEN", "message": exc.message_fa},
            ) from exc
        try:
            record = workflow.create_export(year=year, center=center_value, file_format=format)
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
    async def get_export(request: Request, export_id: str) -> dict[str, object]:
        record = workflow.get_export(export_id)
        if record is None:
            raise HTTPException(status_code=404, detail="EXPORT_NOT_FOUND")
        actor = getattr(request.state, "actor", None)
        if actor is None:
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "توکن نامعتبر است."})
        filters = record.manifest.get("filters", {}) if isinstance(record.manifest, dict) else {}
        center_scope = filters.get("center")
        if isinstance(center_scope, str):
            try:
                center_scope = _parse_center(center_scope)
            except ValueError:
                center_scope = None
        if isinstance(center_scope, float):
            center_scope = int(center_scope)
        try:
            enforce_center_scope(actor, center=center_scope if isinstance(center_scope, int) else None)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "EXPORT_FORBIDDEN", "message": exc.message_fa},
            ) from exc
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
