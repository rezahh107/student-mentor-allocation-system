from __future__ import annotations

import json

from repo_auditor_lite.__main__ import Clock, log


def test_logs_are_persian_and_masked(capsys) -> None:
    clock = Clock()
    log(clock, "cid", "error", error_text="خطای آزمون", user_id="1234567890")
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert payload["timestamp"] == clock.isoformat()
    assert payload["error_text"] == "خطای آزمون"
    assert payload["user_id"].startswith("mask:")
    assert payload["event"] == "error"
