from __future__ import annotations

import io
import zipfile

import pytest

from sma.phase2_uploads.errors import UploadError
from sma.phase2_uploads.zip_utils import iter_csv_from_zip


def _build_zip(entry_name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry_name, "student_id,school_code\r\n1,123\r\n")
    return buffer.getvalue()


@pytest.mark.parametrize(
    "entry",
    ["../evil.csv", "..\\evil.csv", "C:/windows.csv", "C:\\windows.csv", "/abs.csv"],
)
def test_rejects_traversal_and_drive_letters(entry: str) -> None:
    payload = _build_zip(entry)
    with pytest.raises(UploadError) as exc:
        iter_csv_from_zip(payload)
    assert exc.value.envelope.details["reason"] == "ZIP_TRAVERSAL"


def test_valid_csv_stream_is_iterable() -> None:
    payload = _build_zip("students.csv")
    name, stream = iter_csv_from_zip(payload)
    assert name == "students.csv"
    collected = b"".join(stream)
    assert collected.endswith(b"123\r\n")
