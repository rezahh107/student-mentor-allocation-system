from __future__ import annotations

import pandas as pd
import pytest

from app.infra.students.header_resolver import HeaderPipelineV3, STUDENT_HEADER_REGISTRY
from app.infra.students.student_pipeline_v3 import StudentPipelineResult, StudentPipelineV3

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


def assert_qa_payload_schema(payload: list[dict[str, object]]) -> None:
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


def assert_corrupted_payload_fails(
    payload: list[dict[str, object]], missing_key: str
) -> None:
    corrupted = payload.copy()
    corrupted[0] = {key: value for key, value in payload[0].items() if key != missing_key}

    with pytest.raises(AssertionError):
        assert_qa_payload_schema(corrupted)


def test_student_pipeline_v3_group_code_full_matrix_with_complete_qa() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["boy", "girl", "boy", "girl", "boy"],
            "group": ["7", "9", "10", "هنرستان", "12"],
            "grade_level": ["7", "9", "10", "11", "12"],
            "education_level": ["middle", "middle", "high", "technical", "high"],
            "graduation_status": ["current", "درحال تحصیل", "current", "graduated", "dropout"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.can_continue is True
    assert not any(issue.severity == "P0" for issue in result.qa_issues)
    assert_qa_payload_schema(result.qa_payload())


def test_student_pipeline_v3_corrupted_payload_missing_can_continue_or_code() -> None:
    raw = pd.DataFrame({"Gender": ["boy"], "Group": ["7"]})
    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    payload = result.qa_payload()
    assert_qa_payload_schema(payload)

    assert_corrupted_payload_fails(payload, "can_continue")
    assert_corrupted_payload_fails(payload, "code")
    assert_corrupted_payload_fails(payload, "message")


def test_student_pipeline_v3_happy_path_mixed_headers() -> None:
    raw = pd.DataFrame(
        {
            "Gender": ["Male"],
            "گروه": ["11"],
            "متوسطه دوم": ["ignored"],
            "پایه": ["یازدهم"],
            "Graduation Status": ["enrolled"],
            "National ID": ["1234567890"],
            "First Name": ["Ali"],
            "Last Name": ["Karimi"],
            "extra_col": ["noop"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert isinstance(result, StudentPipelineResult)
    assert result.can_continue is True
    assert any(issue.code == "student.header.unknown" for issue in result.qa_issues)

    frame = result.canonical_frame.frame
    assert frame.loc[0, "gender_code"] == 1
    assert frame.loc[0, "group_code"] == "11"
    assert frame.loc[0, "grade_level"] == "11"
    assert frame.loc[0, "graduation_status_code"] == 0


def test_student_pipeline_v3_happy_group_code_integration() -> None:
    raw = pd.DataFrame(
        {
            "Gender": ["girl"],
            "Group": ["9"],
            "graduation_status": ["current"],
            "grade": ["9"],
            "education level": ["متوسطه اول"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.can_continue is True
    assert not any(issue.code.startswith("student.group") and issue.severity == "P1" for issue in result.qa_issues)
    frame = result.canonical_frame.frame
    assert frame.loc[0, "group_code"] == "9"
    assert frame.loc[0, "grade_level"] == "9"
    assert frame.loc[0, "education_level"] == "middle"


def test_student_pipeline_v3_invalid_gender_and_group_block() -> None:
    raw = pd.DataFrame(
        {
            "جنسیت": ["نامشخص"],
            "گروه": [pd.NA],
            "کد ملی": ["999"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.can_continue is False
    assert any(issue.field == "gender_code" and issue.severity == "P0" for issue in result.qa_issues)
    assert any(issue.field == "group_code" and issue.severity == "P0" for issue in result.qa_issues)


def test_student_pipeline_v3_graduation_tokens_are_mapped() -> None:
    raw = pd.DataFrame(
        {
            "Gender": ["F"],
            "Group": ["10"],
            "Graduation Status": ["فارغ التحصیل"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    frame = result.canonical_frame.frame
    assert frame.loc[0, "graduation_status_code"] == 1
    assert result.can_continue is True


def test_student_pipeline_v3_group_level_mismatch_qas() -> None:
    raw = pd.DataFrame(
        {
            "Gender": ["boy"],
            "Group": ["دهم"],
            "پایه": ["9"],
            "education level": ["متوسطه اول"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.can_continue is True
    codes = {issue.code for issue in result.qa_issues}
    assert "student.group.grade_mismatch" in codes
    assert "student.group.education_mismatch" in codes


def test_student_pipeline_v3_group_level_conflict_includes_qa_fields() -> None:
    raw = pd.DataFrame(
        {"gender": ["boy"], "group_code": ["دهم"], "grade": ["9"], "education_level": ["متوسطه اول"]}
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    conflict_issue = next(issue for issue in result.qa_issues if issue.code == "student.group.grade_mismatch")
    assert conflict_issue.severity == "P1"
    assert conflict_issue.field == "grade_level"
    serialized = conflict_issue.as_dict()
    for key in {"rule_id", "code", "severity", "field", "message", "can_continue"}:
        assert key in serialized


def test_student_pipeline_v3_group_code_matrix_with_complete_qa() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["boy", "girl", "girl", "boy"],
            "group": ["7", "9", "هنرستان", "12"],
            "grade_level": ["7", "9", "10", "12"],
            "education_level": ["middle", "middle", "technical", "high"],
            "graduation_status": ["current", "درحال تحصیل", "graduated", "dropout"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.can_continue is True
    assert not any(issue.severity == "P0" for issue in result.qa_issues)

    frame = result.canonical_frame.frame
    assert list(frame["group_code"]) == ["7", "9", "هنرستان", "12"]
    assert list(frame["grade_level"]) == ["7", "9", "10", "12"]
    assert list(frame["education_level"]) == ["middle", "middle", "technical", "high"]

    assert_qa_payload_schema(result.qa_payload())


def test_student_pipeline_v3_edge_group_code_conflicts_and_invalid_tokens() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["x", "boy", "girl"],
            "group": ["دهم", "8", "11"],
            "grade": ["9", "8", "دوازدهم"],
            "education level": ["middle", "high", "متوسطه اول"],
            "graduation_status": ["unknown", "dropout", "فارغ التحصیل"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    codes = {issue.code for issue in result.qa_issues}
    assert "student.group.grade_mismatch" in codes
    assert "student.group.education_mismatch" in codes
    assert any(issue.code == "student.gender.invalid" and issue.severity == "P0" for issue in result.qa_issues)
    assert any(issue.code == "student.graduation.invalid" for issue in result.qa_issues)
    assert result.can_continue is False

    assert_qa_payload_schema(result.qa_payload())


def test_student_pipeline_v3_edge_conflicts_include_rows_and_messages() -> None:
    raw = pd.DataFrame(
        {
            "gender": ["boy", "girl"],
            "group": ["هنرستان", "دهم"],
            "grade": ["8", "11"],
            "education level": ["technical", "middle"],
            "graduation_status": ["current", "unknown"],
        }
    )

    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    grade_mismatch = [issue for issue in result.qa_issues if issue.code == "student.group.grade_mismatch"]
    assert grade_mismatch
    assert all(issue.row is not None for issue in grade_mismatch)
    assert any("conflicts" in issue.message for issue in grade_mismatch)

    codes = {issue.code for issue in result.qa_issues}
    expected_codes = {
        "student.group.grade_mismatch",
        "student.group.education_mismatch",
        "student.graduation.invalid",
    }
    assert expected_codes.issubset(codes)
    assert all(issue.severity == "P1" for issue in result.qa_issues)
    assert result.can_continue is True

    assert_qa_payload_schema(result.qa_payload())


def test_student_pipeline_v3_qa_payload_schema_rejects_missing_fields() -> None:
    raw = pd.DataFrame({"Gender": ["boy"], "Group": ["7"]})
    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    payload = result.qa_payload()
    assert_qa_payload_schema(payload)

    assert_corrupted_payload_fails(payload, "rule_id")
    assert_corrupted_payload_fails(payload, "message")


def test_student_pipeline_v3_qa_payload_schema_rejects_missing_severity_and_field() -> None:
    raw = pd.DataFrame({"Gender": ["boy"], "Group": ["8"]})
    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    payload = result.qa_payload()
    assert_qa_payload_schema(payload)

    assert_corrupted_payload_fails(payload, "severity")
    assert_corrupted_payload_fails(payload, "field")


def test_student_pipeline_v3_qa_payload_shape() -> None:
    raw = pd.DataFrame({"Gender": ["x"], "Group": ["1"]})
    pipeline = StudentPipelineV3()
    result = pipeline.run(raw)

    assert result.qa_issues
    serialized = result.qa_payload()
    for issue in serialized:
        assert {"field", "severity", "code", "rule_id", "message", "row", "can_continue"}.issubset(
            issue.keys()
        )
        assert issue["rule_id"] == issue["code"]


def test_student_header_resolver_uses_shared_registry() -> None:
    pipeline = HeaderPipelineV3(STUDENT_HEADER_REGISTRY)
    student_pipeline = StudentPipelineV3(header_pipeline=pipeline)

    raw = pd.DataFrame({"sex": ["boy"], "group_code": ["7"]})
    result = student_pipeline.run(raw)

    assert result.can_continue is True
    assert student_pipeline._header_resolver.registry is STUDENT_HEADER_REGISTRY
