from __future__ import annotations

"""Streamlit dashboard concentrating on security metrics."""

import ast
from pathlib import Path
from typing import Any, Dict, List

import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sma.core.logging_config import setup_logging

setup_logging()

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAPIException

from sma.security.hardening import SecurityMonitor


def configure_page() -> None:
    """Configure Streamlit page options for the security dashboard."""
    try:
        st.set_page_config(page_title="Security Monitor", layout="wide")
    except StreamlitAPIException:
        pass


configure_page()


ROOT = Path(__file__).resolve().parents[1]
SECURITY_LOG = ROOT / "logs" / "security_events.log"


def load_logged_events(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(ast.literal_eval(line))
        except (ValueError, SyntaxError):
            continue
    return events


def main() -> None:
    st.title("🔒 Security Monitoring Dashboard")

    monitor = SecurityMonitor(str(SECURITY_LOG))
    cached_events = load_logged_events(SECURITY_LOG)
    if cached_events:
        monitor.events.extend(cached_events)

    metrics = monitor.get_security_metrics()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Events", metrics.get("total_events", 0))
    col2.metric("Security Score", metrics.get("security_score", 100))
    severity = metrics.get("severity_counts", {})
    col3.metric("Critical Alerts", severity.get("critical", 0))

    with st.expander("Severity Breakdown", expanded=True):
        st.json(severity)

    top_events = metrics.get("top_event_types", [])
    if top_events:
        df = pd.DataFrame(top_events, columns=["event", "count"])
        st.bar_chart(df.set_index("event"))
    else:
        st.info("No historical events recorded yet.")

    if st.button("Simulate Security Event"):
        monitor.log_event(
            "simulation",
            {"ip": "192.0.2.1", "national_code": "1234567890"},
            "warning",
            "dashboard",
        )
        st.experimental_rerun()


if __name__ == "__main__":
    main()
