from __future__ import annotations

from tools.reqs_doctor.io_utils import atomic_write


def test_atomic_crlf_preserved(doctor_env):
    path = doctor_env.make_namespace("atomic") / "requirements.txt"
    original = "alpha\r\nbeta\r\n"
    path.write_text(original, encoding="utf-8")
    atomic_write(path, "alpha\nbeta\n", clock=doctor_env.clock)
    data = path.read_bytes()
    assert data == original.encode("utf-8"), doctor_env.debug()
