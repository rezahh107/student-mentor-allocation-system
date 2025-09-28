import json

from automation_audit.logging import configure_logging, log_json, set_correlation_id


def test_masking_no_pii(capfd):
    configure_logging()
    set_correlation_id("abc123")
    log_json("msg", email="user@example.com")
    out = capfd.readouterr().err.strip().splitlines()[-1]
    record = json.loads(out)
    assert record["email"].startswith("***")
    assert record["correlation_id"] == "abc123"
