"""Evidence discovery and enforcement for Strict Scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Sequence

from .bootstrap import BootstrapError

PERSIAN_EVIDENCE_ERROR = "شواهد اجباری اجرا نشد؛ لطفاً گزارش pytest را بررسی کنید. :: Mandatory evidence missing; inspect pytest report."


@dataclass(frozen=True)
class EvidenceRequirement:
    """Definition of a spec evidence requirement."""

    key: str
    description: str
    markers: Sequence[str]
    nodeids: Sequence[str]
    agents_sections: Sequence[str]


@dataclass(frozen=True)
class EvidenceResult:
    """Result of evaluating evidence coverage."""

    satisfied: Mapping[str, bool]
    evidence_lines: Mapping[str, Sequence[str]]
    missing: Sequence[str]

    def to_json(self) -> str:
        payload = {
            "satisfied": dict(self.satisfied),
            "evidence": {key: list(value) for key, value in self.evidence_lines.items()},
            "missing": list(self.missing),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class EvidenceLedger:
    """Indexed representation of executed pytest nodes and evidence markers."""

    executed: set[str]
    marker_index: Dict[str, set[str]]

    @classmethod
    def from_pytest_report(cls, data: Mapping[str, object], executed: Iterable[str]) -> "EvidenceLedger":
        marker_index: MutableMapping[str, set[str]] = {}
        tests = data.get("tests", [])
        if isinstance(tests, list):
            for item in tests:
                if not isinstance(item, dict):
                    continue
                if item.get("outcome") != "passed":
                    continue
                nodeid = item.get("nodeid")
                if not isinstance(nodeid, str):
                    continue
                for marker in _extract_markers(item):
                    marker_index.setdefault(marker, set()).add(nodeid)
        return cls(executed=set(executed), marker_index={k: set(v) for k, v in marker_index.items()})


REQUIREMENTS: tuple[EvidenceRequirement, ...] = (
    EvidenceRequirement(
        key="dependency_lock",
        description="Dependency lock enforced via constraints",
        markers=("dependency_lock", "constraints_lock"),
        nodeids=("tests/ci/test_dependency_lock.py::test_constraints_lockfile",),
        agents_sections=("AGENTS.md::Dependency Locking",),
    ),
    EvidenceRequirement(
        key="middleware_order",
        description="Middleware order RateLimit→Idempotency→Auth",
        markers=("middleware_order",),
        nodeids=("tests/mw/test_order_post.py::test_middleware_order_post_exact",),
        agents_sections=("AGENTS.md::Middleware Order",),
    ),
    EvidenceRequirement(
        key="determinism",
        description="Deterministic time guard",
        markers=("determinism",),
        nodeids=("tests/time/test_no_wallclock_repo_guard.py::test_no_wall_clock_calls_in_repo",),
        agents_sections=("AGENTS.md::Determinism",),
    ),
    EvidenceRequirement(
        key="excel_safety",
        description="Excel safety and formula guard",
        markers=("excel_safety",),
        nodeids=("tests/export/test_csv_excel_hygiene.py::test_formula_guard",),
        agents_sections=("AGENTS.md::Excel-Safety & Atomic I/O",),
    ),
    EvidenceRequirement(
        key="atomic_io",
        description="Atomic IO enforced",
        markers=("atomic_io",),
        nodeids=("tests/export/test_atomic_io.py::test_atomic_io",),
        agents_sections=("AGENTS.md::Excel-Safety & Atomic I/O",),
    ),
    EvidenceRequirement(
        key="observability",
        description="Retry and observability metrics emitted",
        markers=("observability", "retry_metrics"),
        nodeids=("tests/obs/test_retry_metrics.py::test_retry_exhaustion_metrics_present",),
        agents_sections=("AGENTS.md::Observability",),
    ),
    EvidenceRequirement(
        key="metrics_guard",
        description="/metrics token guard enforced",
        markers=("metrics_token",),
        nodeids=("tests/security/test_metrics_token_guard.py::test_metrics_endpoint_is_public",),
        agents_sections=("AGENTS.md::Observability & Security",),
    ),
    EvidenceRequirement(
        key="concurrency",
        description="Concurrency guard single success",
        markers=("concurrency",),
        nodeids=("tests/idem/test_concurrent_posts.py::test_only_one_succeeds",),
        agents_sections=("AGENTS.md::Concurrency",),
    ),
    EvidenceRequirement(
        key="redis_hygiene",
        description="Redis hygiene without mid-run flush",
        markers=("state_hygiene", "redis_hygiene"),
        nodeids=(
            "tests/hygiene/test_state_and_registry.py::test_no_midrun_flush",
            "tests/fixtures/test_state_hygiene.py::test_cleanup_and_registry_reset",
        ),
        agents_sections=("AGENTS.md::State Hygiene",),
    ),
    EvidenceRequirement(
        key="coverage_gate",
        description="Coverage gate enforced",
        markers=("coverage_gate",),
        nodeids=("tests/ci/test_ci_pytest_runner.py::test_coverage_gate",),
        agents_sections=("AGENTS.md::Evidence Model",),
    ),
    EvidenceRequirement(
        key="evidence_fallback",
        description="Evidence markers fallback operational",
        markers=("evidence_model", "evidence_fallback"),
        nodeids=("tests/ci/test_ci_pytest_runner.py::test_evidence_markers_fallback",),
        agents_sections=("AGENTS.md::Evidence Model",),
    ),
    EvidenceRequirement(
        key="persian_errors",
        description="Persian error envelopes deterministic",
        markers=("persian_error",),
        nodeids=("tests/i18n/test_persian_errors.py::test_persian_error_envelopes",),
        agents_sections=("AGENTS.md::User-Visible Errors",),
    ),
    EvidenceRequirement(
        key="performance",
        description="Performance budgets respected",
        markers=("performance_budget",),
        nodeids=("tests/perf/test_perf_gates.py::test_p95_latency_and_memory",),
        agents_sections=("AGENTS.md::Performance Budgets",),
    ),
)


def verify_evidence(ledger: EvidenceLedger) -> EvidenceResult:
    satisfied: Dict[str, bool] = {}
    lines: Dict[str, Sequence[str]] = {}
    missing: list[str] = []

    for requirement in REQUIREMENTS:
        executed = _evidence_hits(ledger, requirement)
        if executed:
            satisfied[requirement.key] = True
            lines[requirement.key] = [*sorted(executed), *requirement.agents_sections]
        else:
            satisfied[requirement.key] = False
            lines[requirement.key] = list(requirement.agents_sections)
            missing.append(requirement.description)

    if missing:
        raise BootstrapError(f"{PERSIAN_EVIDENCE_ERROR} :: {' ؛ '.join(missing)}")
    return EvidenceResult(satisfied=satisfied, evidence_lines=lines, missing=tuple())


def _extract_markers(item: Mapping[str, object]) -> Iterable[str]:
    keywords = item.get("keywords")
    if isinstance(keywords, Mapping):
        for key, value in keywords.items():
            if isinstance(key, str) and key.startswith("evidence["):
                yield key.split("[", 1)[1].rstrip("]")
            if isinstance(key, str) and key.startswith("evidence_"):
                yield key.split("_", 1)[1]
            if isinstance(key, str) and key.startswith("evidence") and key not in {"evidence"}:
                marker = key.replace("evidence", "", 1).strip("_:- ")
                if marker:
                    yield marker
            if key == "evidence":
                yield from _normalize_keyword_value(value)
    markers = item.get("markers")
    if isinstance(markers, Mapping):
        evidence = markers.get("evidence")
        yield from _normalize_keyword_value(evidence)


def _normalize_keyword_value(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, str):
                yield item
    elif value is True:
        yield "evidence"


def _evidence_hits(ledger: EvidenceLedger, requirement: EvidenceRequirement) -> set[str]:
    hits: set[str] = set()
    for marker in requirement.markers:
        hits |= ledger.marker_index.get(marker, set())
    if hits:
        return hits
    fallback = {node for node in requirement.nodeids if node in ledger.executed}
    return fallback
