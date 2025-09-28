from pathlib import Path

from automation_audit.exporter import AuditFinding, CSVSafeWriter


def test_excel_safety_streaming(tmp_path: Path):
    path = tmp_path / "export.csv"
    writer = CSVSafeWriter(
        path,
        headers=["automation", "status", "provider", "severity", "message", "remediation"],
    )
    rows = (finding.to_row() for finding in [AuditFinding("ci", "low", "text", automation="ci", status="PASS")])
    writer.write(rows)
    assert path.read_text().startswith("\"automation\"")
