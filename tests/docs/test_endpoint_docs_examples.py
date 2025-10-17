from __future__ import annotations

import json
import re
from uuid import uuid4

from observability.metrics import PerformanceBudgets

from src.tools import cli as cli_module


def test_endpoint_docs_include_payload_examples(tmp_path) -> None:
    namespace = f"docs-{uuid4().hex}"
    with cli_module._build_test_app(namespace) as client:
        schema = client.app.openapi()

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

    # Ensure JSON examples are valid payloads for automation purposes.
    json_blocks = re.findall(r"```json\n(.*?)\n```", markdown, flags=re.DOTALL)
    for payload in json_blocks:
        json.loads(payload)


def test_operations_docs_reference_console_script() -> None:
    budgets = PerformanceBudgets()
    operations_markdown = cli_module.generate_operations_markdown(budgets)
    assert "smasm rotate-keys" in operations_markdown, f"Context: {operations_markdown}"
