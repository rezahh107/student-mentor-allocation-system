from __future__ import annotations

from typing import Any


def assert_log_envelope(payload: dict[str, Any], *, expected_event: str | None = None) -> None:
    missing = {key for key in {"level", "event", "message", "correlation_id"} if key not in payload}
    assert not missing, f"Envelope keys missing: {missing}"
    assert isinstance(payload["correlation_id"], str) and payload["correlation_id"], "correlation_id empty"
    assert isinstance(payload["event"], str) and payload["event"], "event empty"
    assert isinstance(payload["level"], str) and payload["level"], "level empty"
    assert isinstance(payload["message"], str) and payload["message"], "message empty"
    if expected_event:
        assert payload["event"] == expected_event, f"unexpected event: {payload['event']} != {expected_event}"


def parse_json_lines(raw: str) -> list[dict[str, Any]]:
    import json

    lines = [line for line in raw.splitlines() if line.strip()]
    parsed: list[dict[str, Any]] = []
    for line in lines:
        parsed.append(json.loads(line))
    return parsed
