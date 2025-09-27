from __future__ import annotations

import json
import logging

import pytest

from phase6_import_to_sabt.app.logging_config import JSONLogFormatter

pytestmark = pytest.mark.asyncio


async def test_logs_mask_tokens(async_client, caplog):
    with caplog.at_level(logging.INFO):
        logger = logging.getLogger("import-to-sabt.tests")
        logger.info("manual", extra={"token": "abcdef1234", "correlation_id": "manual-1"})
        await async_client.post(
            "/api/jobs",
            headers={
                "Authorization": "Bearer service-token",
                "Idempotency-Key": "log-key",
                "X-Client-ID": "tenant",
                "X-Request-ID": "rid-99",
            },
        )
    formatter = JSONLogFormatter(service_name="import-to-sabt")
    manual_record = next(record for record in caplog.records if record.getMessage() == "manual")
    manual_json = json.loads(formatter.format(manual_record))
    assert manual_json["token"] == "ab***34"
    request_record = next(record for record in caplog.records if record.getMessage() == "request.completed")
    request_json = json.loads(formatter.format(request_record))
    assert request_json["correlation_id"] == "rid-99"
