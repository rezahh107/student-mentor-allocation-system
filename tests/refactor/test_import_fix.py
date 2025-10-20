from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tools import refactor_imports
from tests.refactor.conftest import get_debug_context


def _write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def test_bare_to_src_absolute(tmp_path: Path, clean_state, monkeypatch) -> None:
    root = tmp_path
    _write(root / "AGENTS.md", "# agent spec")
    _write(root / "src/phase6_import_to_sabt/service.py", "def stub() -> None:\n    return None\n")
    _write(root / "src/main.py", "def app():\n    return 'ok'\n")
    _write(root / "app.py", "from phase6_import_to_sabt import service\n")
    _write(root / "run_application.bat", "uvicorn main:app\n")

    report_csv = root / "out" / "report.csv"
    report_json = root / "out" / "report.json"

    runner = CliRunner()
    monkeypatch.chdir(root)
    result = runner.invoke(
        refactor_imports.APP,
        [
            "apply",
            "--report-csv",
            str(report_csv),
            "--report-json",
            str(report_json),
            "--fix-entrypoint",
            "sma.main:app",
        ],
    )
    debug = get_debug_context(clean_state["redis"])
    assert result.exit_code == 0, f"stdout={result.stdout}\nexc={result.exception}\ncontext={debug}"

    updated = (root / "app.py").read_text(encoding="utf-8")
    assert "from sma.phase6_import_to_sabt import service" in updated

    init_file = root / "src/phase6_import_to_sabt/__init__.py"
    assert init_file.exists()

    csv_payload = report_csv.read_bytes()
    assert b"\r\n" in csv_payload

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["fixes"], report
    assert report["fixes"][0]["updated"].startswith("sma."), report

    entrypoint = (root / "run_application.bat").read_text(encoding="utf-8")
    assert "uvicorn sma.main:app" in entrypoint
