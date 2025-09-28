from __future__ import annotations

import io

import pytest

from phase6_import_to_sabt.sanitization import secure_digest


def test_secure_digest_accepts_str_and_bytes() -> None:
    digest_str = secure_digest("نمونه")
    digest_bytes = secure_digest("نمونه".encode("utf-8"))
    assert len(digest_str) == 64
    assert digest_str == digest_bytes


def test_secure_digest_stream_and_iterable(tmp_path) -> None:
    payload = "الفبای فارسی"
    stream = io.BytesIO(payload.encode("utf-8"))
    from_stream = secure_digest(stream)
    stream.seek(0)
    as_iterable = secure_digest([payload[:3], payload[3:]])
    assert from_stream == as_iterable


def test_secure_digest_memoryview() -> None:
    data = memoryview(b"phase6")
    assert secure_digest(data) == secure_digest(b"phase6")


def test_secure_digest_rejects_invalid_source() -> None:
    with pytest.raises(TypeError):
        secure_digest(object())  # type: ignore[arg-type]
