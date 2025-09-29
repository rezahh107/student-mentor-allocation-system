from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from .conftest import AcceptanceChecklistItem, UATScenario


@pytest.mark.usefixtures("frozen_time")
def test_traceability_matrix_complete(
    orchestrator,
    clean_state,
    env_config,
    metrics,
    namespace,
):
    checklist = [
        AcceptanceChecklistItem(
            id="AC-01",
            requirement="پذیرش کاربر با مقادیر تهی",
            spec_reference="SPEC-TRC-01",
            owner="qat",
            evidence_path="reports/evidence/ac01.json",
        ),
        AcceptanceChecklistItem(
            id="AC-02",
            requirement="پذیرش مقادیر بسیار طولانی",
            spec_reference="SPEC-TRC-02",
            owner="qat",
            evidence_path=None,
        ),
    ]
    scenarios = [
        UATScenario(
            scenario_id="SC-001",
            title="ورود اطلاعات ثبت نام",
            description="دریافت فرم با مقادیر تهی و صفر",
            checklist_ids=["AC-01", "AC-02"],
            criticality="HIGH",
            registration_center="۰",  # Persian zero
            registration_status="1",
            owner_phone="۰۹۱۲۱۲۳۴۵۶۷",
            counter_id="143731230",
            academic_year="۱۴۰۲",
        ),
    ]
    plan = orchestrator.generate_uat_plan(
        checklist=checklist,
        scenarios=scenarios,
        correlation_id="rid-phase9-001",
    )
    assert plan[0]["academic_year_code"] == "02"
    assert plan[0]["registration_center"] == "0"
    assert plan[0]["owner_phone"].startswith("09")

    plan_path = clean_state["reports"] / "uat_plan.json"
    csv_path = clean_state["reports"] / "uat_plan.csv"
    trace_matrix = clean_state["docs"] / "traceability_matrix.csv"
    assert plan_path.exists(), plan_path
    assert csv_path.exists(), csv_path
    assert trace_matrix.exists(), trace_matrix

    csv_rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    assert csv_rows[0]["owner_phone"].startswith("'")

    matrix_rows = list(csv.DictReader(trace_matrix.open("r", encoding="utf-8")))
    assert len(matrix_rows) == 2
    assert matrix_rows[0]["correlation_id"] == "rid-phase9-001"

    metrics_samples = metrics.uat_plan_runs.collect()[0].samples
    assert any(sample.labels["namespace"] == env_config.namespace for sample in metrics_samples)

    log_path = clean_state["reports"] / "phase9_readiness.log"
    assert log_path.exists()
    logs = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    assert any(entry.get("event") == "uat.plan.generated" for entry in logs)
