from automation_audit.cli import compute_correlation_id


def test_correlation_12hex(tmp_path):
    cid = compute_correlation_id(tmp_path)
    assert len(cid) == 12
    int(cid, 16)
