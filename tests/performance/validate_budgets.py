from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, asdict
from numbers import Real
from pathlib import Path
from typing import Final

from tests.fixtures.perf import (
    budgets_output_path,
    load_metrics,
    metrics_output_path,
)

P95_BUDGET_SECONDS: Final[float] = 15.0
P99_BUDGET_SECONDS: Final[float] = 20.0
MEMORY_BUDGET_MB: Final[float] = 150.0
DEFAULT_BASELINE_PATH: Final[Path] = Path("tests/performance/baseline.json")


@dataclass(frozen=True)
class BudgetSnapshot:
    label: str
    p95_seconds: float
    p99_seconds: float
    peak_memory_mb: float
    samples: int
    passed: bool

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["budgets"] = {
            "p95_seconds": P95_BUDGET_SECONDS,
            "p99_seconds": P99_BUDGET_SECONDS,
            "peak_memory_mb": MEMORY_BUDGET_MB,
        }
        return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate export performance budgets.")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Path to the baseline budget JSON payload.",
    )
    parser.add_argument(
        "--metrics",
        "--current",
        dest="metrics",
        type=Path,
        default=None,
        help="Path to the metrics JSON file produced by the performance suite.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Optional override for the budgets summary output path.",
    )
    return parser.parse_args()


def _load_metrics_payload(path: Path | None) -> Mapping[str, Mapping[str, Real]]:
    payload = load_metrics(path)
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("Metrics payload missing 'metrics' mapping")
    return metrics  # type: ignore[return-value]


def _load_baseline(path: Path) -> Mapping[str, Mapping[str, Real]]:
    if not path.exists():
        raise FileNotFoundError(f"Baseline file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Baseline file is not valid JSON: {path}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Baseline payload must be a mapping")
    return data  # type: ignore[return-value]


def _p99_from_record(record: Mapping[str, Real]) -> float:
    value = record.get("p99_seconds")
    if isinstance(value, Real):
        return float(value)
    fallback = record.get("max_seconds")
    if isinstance(fallback, Real):
        return float(fallback)
    raise TypeError("missing p99_seconds and max_seconds")


def _peak_mb(record: Mapping[str, Real]) -> float:
    peak_bytes = record.get("peak_memory_bytes", 0.0)
    if not isinstance(peak_bytes, Real):
        raise TypeError("missing peak_memory_bytes")
    return float(peak_bytes) / (1024.0 * 1024.0)


def _extract_snapshots(metrics: Mapping[str, Mapping[str, Real]]) -> Iterable[BudgetSnapshot]:
    tracked_labels: tuple[str, ...] = ("export_100k_budget",)
    for label in tracked_labels:
        record = metrics.get(label)
        if record is None:
            raise KeyError(label)
        p95_value = record.get("p95_seconds")
        if not isinstance(p95_value, Real):
            raise TypeError("missing p95_seconds")
        p99_value = _p99_from_record(record)
        peak_mb = _peak_mb(record)
        samples = int(record.get("samples", 0))
        passed = (
            p95_value <= P95_BUDGET_SECONDS
            and p99_value <= P99_BUDGET_SECONDS
            and peak_mb <= MEMORY_BUDGET_MB
        )
        yield BudgetSnapshot(
            label=label,
            p95_seconds=float(p95_value),
            p99_seconds=p99_value,
            peak_memory_mb=peak_mb,
            samples=samples,
            passed=passed,
        )


def _regressions(
    snapshot: BudgetSnapshot,
    baseline: Mapping[str, Real] | None,
) -> dict[str, float]:
    if baseline is None:
        return {}
    regressions: dict[str, float] = {}
    baseline_p95 = float(baseline.get("p95_seconds", P95_BUDGET_SECONDS))
    baseline_p99 = float(baseline.get("p99_seconds", P99_BUDGET_SECONDS))
    baseline_mem = float(baseline.get("peak_memory_mb", MEMORY_BUDGET_MB))
    if snapshot.p95_seconds > baseline_p95:
        regressions["p95_seconds"] = snapshot.p95_seconds - baseline_p95
    if snapshot.p99_seconds > baseline_p99:
        regressions["p99_seconds"] = snapshot.p99_seconds - baseline_p99
    if snapshot.peak_memory_mb > baseline_mem:
        regressions["peak_memory_mb"] = snapshot.peak_memory_mb - baseline_mem
    return regressions


def _write_summary(
    path: Path,
    snapshots: Iterable[BudgetSnapshot],
    baseline: Mapping[str, Mapping[str, Real]] | None,
) -> tuple[bool, list[dict[str, object]]]:
    items = list(snapshots)
    summary = {
        "results": [],
        "budgets": {
            "p95_seconds": P95_BUDGET_SECONDS,
            "p99_seconds": P99_BUDGET_SECONDS,
            "peak_memory_mb": MEMORY_BUDGET_MB,
        },
        "passed": True,
    }
    for snapshot in items:
        baseline_record = baseline.get(snapshot.label) if baseline else None
        regressions = _regressions(snapshot, baseline_record)
        payload = snapshot.to_payload()
        payload["baseline"] = dict(baseline_record or {})
        payload["regressions"] = regressions
        payload["passed"] = snapshot.passed and not regressions
        summary["passed"] = summary["passed"] and payload["passed"]
        summary["results"].append(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary["passed"], summary["results"]


def main() -> int:
    args = _parse_args()
    metrics_path = args.metrics or metrics_output_path()
    budgets_path = args.summary or budgets_output_path()
    try:
        metrics = _load_metrics_payload(metrics_path)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"❌ Metrics payload invalid: {exc}", file=sys.stderr)
        return 1
    try:
        snapshots = list(_extract_snapshots(metrics))
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Budget extraction failed: {exc}", file=sys.stderr)
        return 1
    baseline = None
    try:
        baseline = _load_baseline(args.baseline)
    except FileNotFoundError as exc:
        print(f"⚠️ Baseline missing: {exc}", file=sys.stderr)
    except ValueError as exc:
        print(f"⚠️ Baseline invalid: {exc}", file=sys.stderr)
    passed, results = _write_summary(budgets_path, snapshots, baseline)
    status = "✅" if passed else "❌"
    for payload in results:
        snapshot = BudgetSnapshot(
            label=str(payload["label"]),
            p95_seconds=float(payload["p95_seconds"]),
            p99_seconds=float(payload["p99_seconds"]),
            peak_memory_mb=float(payload["peak_memory_mb"]),
            samples=int(payload["samples"]),
            passed=bool(payload["passed"]),
        )
        peak = f"peak={snapshot.peak_memory_mb:.1f}MB"
        latency = f"p95={snapshot.p95_seconds:.2f}s, p99={snapshot.p99_seconds:.2f}s"
        regressions = payload.get("regressions", {})
        regression_note = ""
        if regressions:
            regression_note = f" regressions={json.dumps(regressions, ensure_ascii=False)}"
        print(f"{status} {snapshot.label}: {latency}, {peak} (samples={snapshot.samples}){regression_note}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
