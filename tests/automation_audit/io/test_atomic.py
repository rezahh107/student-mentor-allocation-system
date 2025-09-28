from pathlib import Path

from automation_audit.fs_atomic import atomic_write_text


def test_atomic_write(tmp_path: Path):
    path = tmp_path / "file.txt"
    atomic_write_text(path, ["hello", "world"], newline="\n")
    assert path.read_text() == "hello\nworld\n"
