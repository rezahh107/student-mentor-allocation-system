import tracemalloc

from automation_audit.exporter import AuditFinding, render_markdown


def test_memory_ceiling():
    tracemalloc.start()
    findings = [AuditFinding("ci", "low", "msg") for _ in range(1000)]
    render_markdown(findings)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 5 * 10**7
