from __future__ import annotations

import json

import pytest

from sma.phase6_import_to_sabt.logging_utils import ExportLogger


@pytest.fixture
def clean_state():
    yield


def test_pii_masking_with_correlation_id(clean_state, caplog):
    logger = ExportLogger()
    logger.info(
        "job-complete",
        correlation_id="RID-1",
        national_id="0012345678",
        mobile="09120000000",
    )
    record = caplog.records[-1]
    payload = json.loads(record.message)
    assert payload["correlation_id"] == "RID-1"
    assert payload["national_id"].isalnum() and payload["national_id"] != "0012345678"
    assert payload["mobile"].startswith("0912") and payload["mobile"].endswith("00")
