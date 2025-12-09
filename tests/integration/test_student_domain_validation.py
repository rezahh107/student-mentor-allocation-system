from __future__ import annotations

import pandas as pd
import pytest

from app.core.students.canonical_frame import StudentCanonicalFrame
from app.core.students.domain_validation import (
    StudentDomainValidator,
    validate_student_domains,
)
from app.infra.students.student_pipeline_v3 import StudentPipelineV3

# Planned execution (requires Python 3.11.9 + pytest):
# python -m pytest tests/infra/students/test_student_pipeline_v3.py tests/integration/test_student_domain_validation.py


REQUIRED_QA_KEYS: set[str] = {
    "field",
    "severity",
    "code",
    "rule_id",
    "message",
    "row",
    "can_continue",
}


def _assert_qa_payload_schema(payload: list[dict[str, object]]) -> None:
    for idx, issue in enumerate(payload):
        missing = REQUIRED_QA_KEYS - issue.keys()
        assert not missing, f"Missing QA keys {missing} at index {idx}"
        assert isinstance(issue["severity"], str)
        assert isinstance(issue["can_continue"], bool)
        assert isinstance(issue["field"], str)
        assert isinstance(issue["code"], str)
        assert issue.get("rule_id") == issue.get("code")
        assert isinstance(issue["message"], str)
        row_value = issue.get("row")
        assert row_value is None or isinstance(row_value, int)


def _assert_corrupted_payload_fails(
    payload: list[dict[str, object]], missing_key: str
) -> None:
    corrupted = payload.copy()
    corrupted[0] = {key: value for key, value in payload[0].items() if key != missing_key}

    with pytest.raises(AssertionError):
        _assert_qa_payload_schema(corrupted)


def test_missing_join_critical_fields_block_pipeline() -> None:
    canonical = StudentCanonicalFrame.ensure_schema(
        pd.DataFrame(
            {
                "gender_code": [pd.NA],
                "group_code": [pd.NA],
            }
        )
    )

    issues, can_continue = validate_student_domains(
        canonical, validators=(StudentDomainValidator(),)
    )

    assert can_continue is False
    assert any(issue.severity == "P0" and issue.field == "gender_code" for issue in issues)
    assert any(issue.severity == "P0" and issue.field == "group_code" for issue in issues)


def test_integration_pipeline_does_not_change_join_keys() -> None:
    raw = pd.DataFrame(
        {
            "Gender": ["boy"],
            "Group": ["7"],
            "graduation_status": ["current"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)
    frame = result.canonical_frame.frame

    assert frame.loc[0, "gender_code"] == 1
    assert frame.loc[0, "group_code"] == "7"
    assert result.can_continue is True


def test_integration_group_code_parser_alignment() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["دختر"],
            "group": ["هنرستان"],
            "grade_level": [pd.NA],
            "education_level": [pd.NA],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    frame = result.canonical_frame.frame
    assert frame.loc[0, "group_code"] == "هنرستان"
    assert all(issue.severity != "P0" for issue in result.qa_issues)
    assert result.can_continue is True


def test_integration_group_code_matrix_and_qa_payload_schema() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["boy", "girl"],
            "group_code": ["7", "11"],
            "grade_level": ["7", "11"],
            "education_level": ["middle", "high"],
            "graduation_status": ["current", "فارغ التحصیل"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.can_continue is True
    assert not any(issue.severity == "P0" for issue in result.qa_issues)
    _assert_qa_payload_schema(result.qa_payload())


def test_integration_group_code_conflict_emits_expected_qas() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["girl"],
            "group": ["دهم"],
            "grade": ["9"],
            "education_level": ["middle"],
            "graduation_status": ["درحال تحصیل"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    codes = {issue.code for issue in result.qa_issues}
    assert "student.group.grade_mismatch" in codes
    assert "student.group.education_mismatch" in codes
    assert all(issue.severity != "P0" for issue in result.qa_issues)
    assert result.can_continue is True
    _assert_qa_payload_schema(result.qa_payload())


def test_integration_group_code_complex_matrix_and_conflicts() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["boy", "girl", "girl", "x"],
            "group": ["8", "دوازدهم", "هنرستان", "7"],
            "grade": ["8", "11", "8", "7"],
            "education_level": ["middle", "high", "technical", "middle"],
            "graduation_status": ["current", "dropout", "current", "current"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    codes = {issue.code for issue in result.qa_issues}
    assert "student.group.grade_mismatch" in codes
    assert "student.gender.unknown_token" in codes
    assert "student.gender.missing" in codes
    assert any(
        issue.code == "student.gender.unknown_token" and issue.severity == "P1"
        for issue in result.qa_issues
    )
    assert any(
        issue.code == "student.gender.missing" and issue.severity == "P0" for issue in result.qa_issues
    )
    assert any(issue.code == "student.group.grade_mismatch" and issue.row is not None for issue in result.qa_issues)
    assert result.can_continue is False

    _assert_qa_payload_schema(result.qa_payload())


def test_integration_qa_payload_schema_corruption_detection() -> None:
    raw = pd.DataFrame({"Gender": ["boy"], "Group": ["7"]})
    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    payload = result.qa_payload()
    _assert_qa_payload_schema(payload)

    _assert_corrupted_payload_fails(payload, "rule_id")
    _assert_corrupted_payload_fails(payload, "severity")
    _assert_corrupted_payload_fails(payload, "field")
    _assert_corrupted_payload_fails(payload, "can_continue")
    _assert_corrupted_payload_fails(payload, "code")
    _assert_corrupted_payload_fails(payload, "message")
