from __future__ import annotations

from pathlib import Path


def test_warnings_are_errors() -> None:
    ini_path = Path("pytest.ini")
    assert ini_path.exists(), "pytest.ini must exist for warnings policy"
    text = ini_path.read_text(encoding="utf-8")
    assert "filterwarnings" in text
    assert any(line.strip() == "error" for line in text.splitlines()), "Warnings should be treated as errors"
