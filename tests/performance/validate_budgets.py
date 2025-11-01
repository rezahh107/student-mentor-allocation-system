"""Validate export performance metrics against budgets and baselines."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

P95_BUDGET_SECONDS = 15.0
P99_BUDGET_SECONDS = 20.0
MEMORY_BUDGET_MB = 150.0
DEFAULT_SUMMARY_PATH = Path("test-results/export_perf.json")
DEFAULT_BASELINE_PATH = Path("tests/performance/baseline.json")
REQUIRED_ROWS = 100_000


@dataclass(frozen=True)
class BudgetEvaluation:
    label: str
    p95_seconds: float
    p99_seconds: float
    peak_memory_mb: float
    samples: int
    regressions: Mapping[str, float]
    passed: bool

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "label": self.label,
            "p95_seconds": self.p95_seconds,
            "p99_seconds": self.p99_seconds,
            "peak_memory_mb": self.peak_memory_mb,
            "samples": self.samples,
            "regressions": dict(self.regressions),
            "passed": self.passed,
            "budgets": {
                "p95_seconds": P95_BUDGET_SECONDS,
                "p99_seconds": P99_BUDGET_SECONDS,
                "peak_memory_mb": MEMORY_BUDGET_MB,
            },
        }
        return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate XLSX export budgets.")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Path to the baseline JSON payload.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Path to the measured performance summary JSON.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")  # noqa: TRY003
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise TypeError(f"Payload must be a mapping: {path}")  # noqa: TRY003
    return data


def _extract_metrics(
    summary: Mapping[str, Any],
) -> tuple[str, float, float, float, int]:
    label = str(summary.get("label", "export_100k_budget"))
    p95 = float(
        summary.get(
            "latency_p95_seconds",
            summary.get("p95_seconds", 0.0),
        )
    )
    p99 = float(
        summary.get(
            "latency_p99_seconds",
            summary.get("p99_seconds", 0.0),
        )
    )
    peak_mb = float(summary.get("peak_memory_mb", 0.0))
    samples = int(summary.get("samples", 0))
    return label, p95, p99, peak_mb, samples


def _budgets_passed(p95: float, p99: float, peak_mb: float) -> bool:
    return (
        p95 <= P95_BUDGET_SECONDS
        and p99 <= P99_BUDGET_SECONDS
        and peak_mb <= MEMORY_BUDGET_MB
    )


def _worse(current: float, reference: float, tolerance: float = 0.05) -> bool:
    return current > reference * (1 + tolerance)


def _compare_to_baseline(
    label: str,
    p95: float,
    p99: float,
    peak_mb: float,
    baseline: Mapping[str, Mapping[str, float]] | None,
) -> Mapping[str, float]:
    if baseline is None:
        return {}
    record = baseline.get(label)
    if record is None:
        return {}
    regressions: dict[str, float] = {}
    baseline_p95 = float(record.get("p95_seconds", P95_BUDGET_SECONDS))
    baseline_p99 = float(record.get("p99_seconds", P99_BUDGET_SECONDS))
    baseline_mem = float(record.get("peak_memory_mb", MEMORY_BUDGET_MB))

    if _worse(p95, baseline_p95):
        regressions["p95_seconds"] = p95 - baseline_p95
    if _worse(p99, baseline_p99):
        regressions["p99_seconds"] = p99 - baseline_p99
    if _worse(peak_mb, baseline_mem):
        regressions["peak_memory_mb"] = peak_mb - baseline_mem
    return regressions


def _evaluate(
    summary: Mapping[str, Any],
    baseline: Mapping[str, Mapping[str, float]] | None,
) -> BudgetEvaluation:
    label, p95, p99, peak_mb, samples = _extract_metrics(summary)
    rows = int(summary.get("rows_per_attempt", 0))
    regressions = dict(_compare_to_baseline(label, p95, p99, peak_mb, baseline))
    if rows < REQUIRED_ROWS:
        regressions["rows_per_attempt"] = float(rows)
    passed = (
        _budgets_passed(p95, p99, peak_mb)
        and rows >= REQUIRED_ROWS
        and not regressions
    )
    return BudgetEvaluation(
        label=label,
        p95_seconds=p95,
        p99_seconds=p99,
        peak_memory_mb=peak_mb,
        samples=samples,
        regressions=regressions,
        passed=passed,
    )


def _write_augmented_summary(
    path: Path,
    summary: Mapping[str, Any],
    evaluation: BudgetEvaluation,
    baseline: Mapping[str, Mapping[str, float]] | None,
) -> None:
    payload = dict(summary)
    payload["baseline"] = dict((baseline or {}).get(evaluation.label, {}))
    payload.update(evaluation.as_payload())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    try:
        summary_payload = _load_json(args.summary)
    except (FileNotFoundError, TypeError, json.JSONDecodeError) as exc:
        print(f"❌ Failed to load summary: {exc}", file=sys.stderr)
        return 1
    try:
        baseline_payload = _load_json(args.baseline)
    except FileNotFoundError as exc:
        print(f"⚠️ Baseline missing: {exc}", file=sys.stderr)
        baseline_payload = None
    except (TypeError, json.JSONDecodeError) as exc:
        print(f"⚠️ Baseline invalid: {exc}", file=sys.stderr)
        baseline_payload = None

    evaluation = _evaluate(summary_payload, baseline_payload)
    _write_augmented_summary(
        args.summary,
        summary_payload,
        evaluation,
        baseline_payload,
    )

    status = "✅" if evaluation.passed else "❌"
    note = ""
    if evaluation.regressions:
        regressions_payload = json.dumps(
            dict(evaluation.regressions),
            ensure_ascii=False,
        )
        note = f" regressions={regressions_payload}"
    print(
        f"{status} {evaluation.label}: p95={evaluation.p95_seconds:.2f}s, "
        f"p99={evaluation.p99_seconds:.2f}s, peak={evaluation.peak_memory_mb:.1f}MB "
        f"(samples={evaluation.samples}){note}"
    )
    return 0 if evaluation.passed else 1


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main())
