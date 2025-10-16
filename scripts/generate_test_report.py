from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List
import xml.etree.ElementTree as ET


def _percentile(data: Iterable[float], percentile: float) -> float:
    values = sorted(float(item) for item in data if item is not None)
    if not values:
        return 0.0
    rank = max(0, math.ceil((percentile / 100.0) * len(values)) - 1)
    return values[min(rank, len(values) - 1)]


def load_coverage(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"total": 0.0, "modules": []}
    tree = ET.parse(path)
    root = tree.getroot()
    total = float(root.get("line-rate", 0.0)) * 100
    modules: List[Dict[str, Any]] = []
    for package in root.findall(".//package"):
        name = package.get("name", "")
        line_rate = float(package.get("line-rate", 0.0)) * 100
        modules.append({"name": name, "coverage": line_rate})
    modules.sort(key=lambda item: item["coverage"], reverse=True)
    return {"total": total, "modules": modules}


def load_pytest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"summary": {}, "slow": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    tests = data.get("tests", [])
    slow = sorted(tests, key=lambda item: item.get("duration", 0.0), reverse=True)[:10]
    return {"summary": summary, "slow": slow}


def load_benchmarks(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    benchmarks: List[Dict[str, Any]] = []
    for bench in data.get("benchmarks", []):
        stats = bench.get("stats", {})
        samples = stats.get("data", [])
        benchmarks.append(
            {
                "name": bench.get("name", "unknown"),
                "rounds": stats.get("rounds", 0),
                "ops": stats.get("ops", 0.0),
                "min": stats.get("min", 0.0),
                "max": stats.get("max", 0.0),
                "mean": stats.get("mean", 0.0),
                "p95": _percentile(samples, 95),
            }
        )
    benchmarks.sort(key=lambda item: item["p95"])
    return benchmarks


def load_perf_metrics(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    metrics: List[Dict[str, Any]] = []
    for label, payload in data.get("metrics", {}).items():
        metrics.append(
            {
                "label": label,
                "samples": payload.get("samples", 0),
                "p95": payload.get("p95_seconds", 0.0),
                "mean": payload.get("mean_seconds", 0.0),
                "max": payload.get("max_seconds", 0.0),
                "peak_memory": payload.get("peak_memory_bytes", 0),
            }
        )
    metrics.sort(key=lambda item: item["label"])
    return metrics


def build_markdown(
    *,
    coverage: Dict[str, Any],
    pytest_data: Dict[str, Any],
    benchmarks: List[Dict[str, Any]],
    perf_metrics: List[Dict[str, Any]],
) -> str:
    lines: List[str] = ["# Windows CI Test Report", ""]
    total_cov = coverage.get("total", 0.0)
    lines.append(f"**Total coverage:** {total_cov:.2f}%")
    summary = pytest_data.get("summary", {})
    if summary:
        lines.append(
            f"**Pytest summary:** passed={summary.get('passed', 0)}, failed={summary.get('failed', 0)}, "
            f"skipped={summary.get('skipped', 0)}, warnings={summary.get('warnings', 0)}"
        )
    lines.append("")

    modules = coverage.get("modules", [])[:10]
    if modules:
        lines.append("## Coverage by Module")
        lines.append("| Package | Coverage |")
        lines.append("| --- | --- |")
        for module in modules:
            lines.append(f"| {module['name']} | {module['coverage']:.2f}% |")
        lines.append("")

    if perf_metrics:
        lines.append("## Performance Metrics")
        lines.append("| Scenario | Samples | p95 (s) | Mean (s) | Max (s) | Peak Memory (MB) |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for metric in perf_metrics:
            peak_mb = metric["peak_memory"] / (1024 * 1024)
            lines.append(
                "| {label} | {samples} | {p95:.3f} | {mean:.3f} | {max:.3f} | {peak:.1f} |".format(
                    label=metric["label"],
                    samples=metric["samples"],
                    p95=metric["p95"],
                    mean=metric["mean"],
                    max=metric["max"],
                    peak=peak_mb,
                )
            )
        lines.append("")

    if benchmarks:
        lines.append("## Benchmark Results")
        lines.append("| Benchmark | Rounds | Mean (s) | p95 (s) | Min (s) | Max (s) | Ops/s |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for bench in benchmarks:
            lines.append(
                "| {name} | {rounds} | {mean:.4f} | {p95:.4f} | {min:.4f} | {max:.4f} | {ops:.2f} |".format(
                    name=bench["name"],
                    rounds=bench["rounds"],
                    mean=bench["mean"],
                    p95=bench["p95"],
                    min=bench["min"],
                    max=bench["max"],
                    ops=bench["ops"],
                )
            )
        lines.append("")

    slow_tests = pytest_data.get("slow", [])
    if slow_tests:
        lines.append("## Slowest Tests")
        lines.append("| Test | Duration (s) | Outcome |")
        lines.append("| --- | ---: | --- |")
        for test in slow_tests:
            lines.append(
                "| {nodeid} | {duration:.3f} | {outcome} |".format(
                    nodeid=test.get("nodeid", ""),
                    duration=test.get("duration", 0.0),
                    outcome=test.get("outcome", "unknown"),
                )
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_badge(path: Path, coverage: float) -> None:
    if coverage >= 90:
        color = "#4c1"
    elif coverage >= 80:
        color = "#a4a61d"
    elif coverage >= 70:
        color = "#dfb317"
    else:
        color = "#e05d44"
    text = f"{coverage:.1f}%"
    width = 120
    svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='20' role='img' aria-label='coverage: {text}'>
  <linearGradient id='smooth' x2='0' y2='100%'>
    <stop offset='0' stop-color='#bbb' stop-opacity='.1'/>
    <stop offset='1' stop-opacity='.1'/>
  </linearGradient>
  <mask id='round'>
    <rect width='{width}' height='20' rx='3' fill='#fff'/>
  </mask>
  <g mask='url(#round)'>
    <rect width='70' height='20' fill='#555'/>
    <rect x='70' width='{width - 70}' height='20' fill='{color}'/>
    <rect width='{width}' height='20' fill='url(#smooth)'/>
  </g>
  <g fill='#fff' text-anchor='middle' font-family='DejaVu Sans,Verdana,Geneva,sans-serif' font-size='11'>
    <text x='35' y='14'>coverage</text>
    <text x='{70 + (width - 70) / 2}' y='14'>{text}</text>
  </g>
</svg>
""".strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate consolidated CI test report")
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--pytest-json", type=Path, required=True)
    parser.add_argument("--bench-json", type=Path, required=True)
    parser.add_argument("--perf-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--badge", type=Path, required=True)
    args = parser.parse_args()

    coverage = load_coverage(args.coverage)
    pytest_data = load_pytest(args.pytest_json)
    benchmarks = load_benchmarks(args.bench_json)
    perf_metrics = load_perf_metrics(args.perf_json)

    report = build_markdown(
        coverage=coverage,
        pytest_data=pytest_data,
        benchmarks=benchmarks,
        perf_metrics=perf_metrics,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    write_badge(args.badge, coverage.get("total", 0.0))


if __name__ == "__main__":
    main()
