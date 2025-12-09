from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from app.core.students.canonical_frame import StudentCanonicalFrame
from app.core.students.domain_validation import QAIssue, StudentDomainValidator, validate_student_domains
from app.infra.students.header_resolver import HeaderPipelineV3, StudentHeaderResolver, STUDENT_HEADER_REGISTRY
from app.infra.students.value_canonicalizer import StudentValueCanonicalizer


@dataclass(frozen=True)
class StudentPipelineResult:
    canonical_frame: StudentCanonicalFrame
    qa_issues: list[QAIssue]
    can_continue: bool

    def qa_payload(self) -> list[dict[str, object]]:
        """Return QA issues serialized for HistoryStore/QA consumers."""

        return [issue.as_dict() for issue in self.qa_issues]


class StudentPipelineV3:
    """Single entrypoint for student imports using v3 pipelines."""

    def __init__(
        self,
        *,
        header_resolver: StudentHeaderResolver | None = None,
        value_canonicalizer: StudentValueCanonicalizer | None = None,
        validators: Sequence[StudentDomainValidator] | None = None,
        header_pipeline: HeaderPipelineV3 | None = None,
    ) -> None:
        pipeline = header_pipeline or HeaderPipelineV3(STUDENT_HEADER_REGISTRY)
        self._header_resolver = header_resolver or StudentHeaderResolver(pipeline)
        self._value_canonicalizer = value_canonicalizer or StudentValueCanonicalizer()
        self._validators = validators

    def run(self, df: pd.DataFrame) -> StudentPipelineResult:
        resolved, header_issues = self._header_resolver.resolve(df)
        canonical_df, canonicalization_issues = self._value_canonicalizer.canonicalize(resolved)
        canonical_frame = StudentCanonicalFrame.ensure_schema(canonical_df)

        validation_issues, validation_can_continue = validate_student_domains(
            canonical_frame, validators=self._validators
        )

        qa_issues = [*header_issues, *canonicalization_issues, *validation_issues]
        can_continue = validation_can_continue and all(
            issue.can_continue for issue in qa_issues
        )
        return StudentPipelineResult(
            canonical_frame=canonical_frame,
            qa_issues=qa_issues,
            can_continue=can_continue,
        )
