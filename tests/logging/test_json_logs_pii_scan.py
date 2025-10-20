from __future__ import annotations

import json
import logging
import uuid

from sma.phase6_import_to_sabt.app.logging_config import configure_logging


def test_no_pii_in_logs(capfd) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    try:
        configure_logging("import-to-sabt-test", enable_debug=True)
        logger = logging.getLogger("import.to.sabt")
        correlation_id = f"cid-{uuid.uuid4().hex}"
        logger.info(
            "student.updated",
            extra={
                "correlation_id": correlation_id,
                "mobile": "09123456789",
                "national_id": "1234567890",
                "mentor_id": "AB1234567",
            },
        )
        out, _ = capfd.readouterr()
        lines = [line for line in out.splitlines() if line.strip()]
        assert lines, "Expected JSON log lines to be emitted"
        payload = json.loads(lines[-1])
        debug = {"raw": lines[-1], "payload": payload}
        assert payload["correlation_id"] == correlation_id, debug
        assert payload["message"] == "student.updated", debug
        assert payload["mobile"] != "09123456789", debug
        assert payload["national_id"] != "1234567890", debug
        assert payload["mentor_id"] != "AB1234567", debug
        assert "09123456789" not in lines[-1], debug
        assert "1234567890" not in lines[-1], debug
        assert "AB1234567" not in lines[-1], debug
    finally:
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
