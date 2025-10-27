from __future__ import annotations

from hashlib import sha256

from sma.phase2_uploads.storage import AtomicStorage



def test_finalize_writes_and_cleans_partials(tmp_path) -> None:
    storage = AtomicStorage(tmp_path)
    writer = storage.writer()
    payload = b"alpha,beta\r\n1,2\r\n"
    writer.write(payload)
    digest = sha256(payload).hexdigest()
    final_path = storage.finalize(digest, writer)
    assert final_path.read_bytes() == payload
    assert final_path == storage.path_for_digest(digest)
    assert not list((storage.base_dir / "tmp").glob("*.part"))

    second = storage.writer()
    second.write(b"ignored")
    same_path = storage.finalize(digest, second)
    assert same_path == final_path
    assert same_path.read_bytes() == payload
    assert not list((storage.base_dir / "tmp").glob("*.part"))
