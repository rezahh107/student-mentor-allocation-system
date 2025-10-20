from __future__ import annotations

import json
import logging

from sma.phase6_import_to_sabt.logging_utils import ExportLogger


def test_masking_and_correlation_id(caplog):
    logger = ExportLogger(logging.getLogger("phase6.test"))
    with caplog.at_level(logging.INFO):
        logger.info(
            "export_completed",
            correlation_id="rid-42",
            mobile="09123456789",
            national_id="1234567890",
        )
    record = caplog.records[0]
    payload = json.loads(record.getMessage())
    assert payload["correlation_id"] == "rid-42"
    assert payload["mobile"].startswith("0912") and payload["mobile"].endswith("89")
    assert payload["national_id"] != "1234567890"
