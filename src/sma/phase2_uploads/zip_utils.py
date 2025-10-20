from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Tuple

from .errors import UploadError, envelope

MAX_MEMBERS = 10
MAX_COMPRESSED_RATIO = 50


@dataclass(slots=True)
class ZipCSVStream:
    filename: str
    _data: bytes

    def __iter__(self) -> Iterator[bytes]:
        with zipfile.ZipFile(io.BytesIO(self._data)) as zf:
            info = _select_csv_info(zf, expected_filename=self.filename)
            with zf.open(info, "r") as member:
                while True:
                    chunk = member.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk


def _select_csv_info(
    zf: zipfile.ZipFile, *, expected_filename: str | None = None
) -> zipfile.ZipInfo:
    members = zf.infolist()
    if len(members) > MAX_MEMBERS:
        raise UploadError(
            envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "ZIP_TOO_MANY_MEMBERS"})
        )
    csv_infos = [info for info in members if info.filename.lower().endswith(".csv")]
    if not csv_infos:
        raise UploadError(
            envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "CSV_NOT_FOUND"})
        )
    info = csv_infos[0]
    if expected_filename and info.filename != expected_filename:
        raise UploadError(
            envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "ZIP_CHANGED"})
        )
    path = Path(info.filename)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise UploadError(
            envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "ZIP_TRAVERSAL"})
        )
    if info.file_size and info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSED_RATIO:
        raise UploadError(
            envelope("UPLOAD_VALIDATION_ERROR", details={"reason": "ZIP_BOMB"})
        )
    return info


def iter_csv_from_zip(data: bytes) -> Tuple[str, ZipCSVStream]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = _select_csv_info(zf)
    except zipfile.BadZipFile as exc:  # pragma: no cover - defensive
        raise UploadError(envelope("UPLOAD_FORMAT_UNSUPPORTED")) from exc
    return info.filename, ZipCSVStream(filename=info.filename, _data=data)
