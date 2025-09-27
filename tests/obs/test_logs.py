from __future__ import annotations

import json
import logging

from phase6_import_to_sabt.logging_utils import get_export_logger


def test_pii_masking(caplog):
    logger = get_export_logger()
    with caplog.at_level(logging.INFO):
        logger.info("event", national_id="0012345678", mobile="09123456789")
    record = caplog.records[0]
    payload = json.loads(record.message)
    assert payload["national_id"] != "0012345678"
    assert payload["mobile"].startswith("0912")
    assert payload["mobile"].endswith("89")
