from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics

from sma.tools import cli as cli_module


def _build_app(namespace: str):
    config = cli_module._ensure_env(namespace)
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    metrics = build_metrics(f"{namespace}_metrics")
    timer = DeterministicTimer([0.01, 0.02, 0.03])
    rate_store = InMemoryKeyValueStore(f"{namespace}:rate", clock)
    idem_store = InMemoryKeyValueStore(f"{namespace}:idem", clock)
    return create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
    )


def test_endpoint_docs_include_payload_examples() -> None:
    namespace = f"docs_{uuid4().hex}"
    app = _build_app(namespace)
    schema = app.openapi()

    markdown = cli_module.generate_endpoint_markdown(schema)
    assert "**Request Example**" in markdown, f"Context: {markdown[:400]}"
    assert "**Response Example" in markdown, f"Context: {markdown[:400]}"
    assert "Content-Type: application/json" in markdown

    metrics_sections = [
        block for block in markdown.split("## ") if block.startswith("`GET /metrics`")
    ]
    assert metrics_sections, f"Context: metrics block missing -> {markdown}"
    metrics_block = metrics_sections[0]
    expected_header = f"X-Metrics-Token: {cli_module.DEFAULT_TOKENS[1]['value']}"
    assert expected_header in metrics_block, f"Context: {metrics_block}"

    json_blocks = re.findall(r"```json\n(.*?)\n```", markdown, flags=re.DOTALL)
    for payload in json_blocks:
        json.loads(payload)


def test_operations_docs_reference_console_script() -> None:
    budgets = cli_module.PerformanceBudgets()
    operations_markdown = cli_module.generate_operations_markdown(budgets)
    assert "smasm rotate-keys" in operations_markdown, f"Context: {operations_markdown}"
