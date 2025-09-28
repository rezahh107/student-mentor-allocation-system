from __future__ import annotations

import io
import zipfile

import pytest

from phase2_uploads.errors import UploadError
from phase2_uploads.service import UploadContext


def make_zip(filename: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, data)
    return buffer.getvalue()


def test_reject_traversal_and_zip_bomb(service):
    traversal_zip = make_zip("../evil.csv", b"id,school_code\r\n1,1\r\n")
    context = UploadContext(
        profile="ROSTER_V1",
        year=1400,
        filename="upload.zip",
        rid="RID-ZIP-1",
        namespace="zip-tests",
        idempotency_key="zip-1",
    )
    with pytest.raises(UploadError) as exc:
        service.upload(context, io.BytesIO(traversal_zip))
    assert exc.value.envelope.details["reason"] == "ZIP_TRAVERSAL"

    bomb_data = b"0" * (512 * 1024)
    bomb_zip = make_zip("safe.csv", bomb_data)
    context2 = UploadContext(
        profile="ROSTER_V1",
        year=1400,
        filename="upload.zip",
        rid="RID-ZIP-2",
        namespace="zip-tests",
        idempotency_key="zip-2",
    )
    with pytest.raises(UploadError) as exc2:
        service.upload(context2, io.BytesIO(bomb_zip))
    assert exc2.value.envelope.details["reason"] == "ZIP_BOMB"
