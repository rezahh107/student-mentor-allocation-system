from pathlib import Path

from automation_audit.exporter import AuditFinding, CSVSafeWriter


def test_always_quote_and_guard(tmp_path: Path):
    path = tmp_path / "report.csv"
    writer = CSVSafeWriter(path, headers=["provider", "severity", "message"])
    writer.write([{"provider": "ci", "severity": "high", "message": "=rm"}])
    content = path.read_text(encoding="utf-8")
    assert '"\'=rm"' in content
