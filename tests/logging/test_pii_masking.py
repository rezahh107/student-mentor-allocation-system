import json
import logging

from phase6_import_to_sabt.logging_utils import ExportLogger


def test_no_plain_mobile_in_logs(caplog) -> None:
    logger = ExportLogger(logging.getLogger(f"pii-test"))
    with caplog.at_level(logging.INFO):
        logger.info(
            "export_completed",
            correlation_id="rid-1",
            mobile="09121234567",
            national_id="1234567890",
        )
    assert caplog.records, "Expected log records for masking test"
    payload = json.loads(caplog.records[0].message)
    assert payload["mobile"].startswith("0912") and payload["mobile"].endswith("67")
    assert payload["mobile"] != "09121234567"
    assert payload["national_id"] != "1234567890"
    assert payload["correlation_id"] == "rid-1"
