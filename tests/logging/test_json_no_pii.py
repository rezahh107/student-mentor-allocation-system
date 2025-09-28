from __future__ import annotations

from io import StringIO

from phase2_uploads.logging_utils import hash_national_id, mask_mobile, setup_json_logging


def test_logs_mask_mobile_hash_national_id():
    logger = setup_json_logging()
    handler = logger.handlers[0]
    original_stream = handler.stream
    buffer = StringIO()
    handler.stream = buffer
    logger.info(
        "upload",
        extra={
            "ctx_rid": "RID-PII",
            "ctx_op": "test",
            "ctx_mobile": mask_mobile("09123456789"),
            "ctx_national_id": hash_national_id("0012345678"),
        },
    )
    handler.flush()
    handler.stream = original_stream
    out = buffer.getvalue().strip().splitlines()[-1]
    assert "0912*****89" in out
    assert "RID-PII" in out
