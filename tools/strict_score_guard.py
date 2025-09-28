#!/usr/bin/env python3
"""Utility to guarantee Strict Score artifact creation across CI phases."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from tools.strict_score_core import (
    EvidenceMatrix,
    ScoreEngine,
    build_quality_report,
    detect_repo_features,
    gather_quality_validations,
    merge_feature_sources,
    scan_todo_markers,
)
from tools.strict_score_reporter import (
    StrictMetadata,
    StrictScoreLogger,
    StrictScoreMetrics,
    StrictScoreWriter,
    build_fallback_payload,
    build_real_payload_from_score,
    parse_pytest_summary_extended,
)


PHASES = {"install", "test", "all", "synthesize"}


def _load_text_from_path(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return ""


def _gather_summary_text(paths: Iterable[Path], inline: Sequence[str]) -> str:
    chunks: List[str] = []
    for entry in inline:
        if entry:
            chunks.append(entry)
    for path in paths:
        if not path:
            continue
        text = _load_text_from_path(path)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _determine_phase(value: Optional[str]) -> str:
    if value and value in PHASES:
        return value
    return "synthesize"


def _resolve_json_path(arg_path: Optional[str]) -> Path:
    if arg_path:
        return Path(arg_path)
    env_value = os.environ.get("STRICT_SCORE_JSON", "reports/strict_score.json")
    return Path(env_value)


def _correlation_seed() -> str:
    for key in ("X_REQUEST_ID", "CI_CORRELATION_ID", "GITHUB_RUN_ID"):
        value = os.environ.get(key)
        if value:
            return value
    return os.environ.get("HOSTNAME", "strict-ci")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ensure reports/strict_score.json exists")
    parser.add_argument("--phase", choices=sorted(PHASES), help="CI phase invoking the guard")
    parser.add_argument(
        "--summary-file",
        action="append",
        default=[],
        help="Optional file containing pytest output to parse",
    )
    parser.add_argument(
        "--summary-text",
        action="append",
        default=[],
        help="Inline snippet with pytest tail lines",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        help="Explicit path for strict score JSON (defaults to STRICT_SCORE_JSON)",
    )
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help="Skip writing when the target file already exists",
    )
    parser.add_argument(
        "--correlation-id",
        help="Override correlation identifier (defaults to env derived value)",
    )
    parser.add_argument(
        "--evidence-file",
        action="append",
        default=[],
        help="Optional evidence declaration file (json or markdown)",
    )
    parser.add_argument(
        "--exit-code",
        type=int,
        default=0,
        help="Pytest exit code to enforce in scoring",
    )
    args = parser.parse_args(argv)

    phase = _determine_phase(args.phase)
    target = _resolve_json_path(args.json_path)

    summary_paths = [Path(item) for item in args.summary_file]
    env_summary = os.environ.get("PYTEST_SUMMARY_PATH")
    if env_summary:
        summary_paths.append(Path(env_summary))
    inline = list(args.summary_text)
    env_inline = os.environ.get("PYTEST_SUMMARY")
    if env_inline:
        inline.append(env_inline)

    summary_text = _gather_summary_text(summary_paths, inline)
    counts, found = parse_pytest_summary_extended(summary_text)

    correlation_id = args.correlation_id or hashlib.sha256(_correlation_seed().encode("utf-8")).hexdigest()[:16]
    logger = StrictScoreLogger(stream=sys.stdout, correlation_id=correlation_id)
    metrics = StrictScoreMetrics()
    metadata = StrictMetadata(
        phase=phase,
        correlation_id=correlation_id,
        clock_seed=os.environ.get("STRICT_SCORE_CLOCK_SEED", phase),
        path=target,
        pythonwarnings=os.environ.get("PYTHONWARNINGS", ""),
    )
    writer = StrictScoreWriter(logger=logger, metrics=metrics)

    if args.if_missing and target.exists():
        logger.info("strict_report.skip_existing", path=str(target), phase=phase)
        return 0

    repo_root = Path.cwd()
    evidence = EvidenceMatrix()
    evidence_paths = [Path(item) for item in args.evidence_file]
    env_evidence = os.environ.get("STRICT_SCORE_EVIDENCE_FILE")
    if env_evidence:
        evidence_paths.append(Path(env_evidence))
    evidence.load_many(evidence_paths)

    detected_features = detect_repo_features(repo_root)
    features = merge_feature_sources(detected=detected_features, evidence=evidence)
    todo_count = scan_todo_markers(repo_root)

    score_engine = ScoreEngine(gui_in_scope=features.get("gui_scope", False), evidence=evidence)
    spec_statuses = score_engine.apply_evidence_matrix()
    score_engine.apply_feature_flags(features)
    score_engine.apply_todo_count(todo_count)
    score_engine.apply_pytest_result(summary=counts, returncode=args.exit_code)
    score_engine.apply_state(redis_error=None)

    synth_reason = "گزارش pytest در دسترس نبود؛ گزارش جایگزین ساخته شد"
    mode = "real" if found else "synth"
    if not found:
        score_engine.cap(85, synth_reason)

    score = score_engine.finalize()
    if mode == "real":
        payload = build_real_payload_from_score(
            score=score,
            summary=counts,
            metadata=metadata,
            evidence_matrix=evidence,
            spec_statuses=spec_statuses,
        )
    else:
        payload = build_fallback_payload(
            metadata=metadata,
            counts=counts,
            score=score,
            evidence_matrix=evidence,
            spec_statuses=spec_statuses,
            message=synth_reason,
        )

    try:
        writer.write(path=target, payload=payload, mode=mode)
    except Exception as exc:  # pragma: no cover - fatal guard failure
        logger.error("strict_report.write_failed", error=str(exc), path=str(target), phase=phase)
        return 1

    logger.info(
        "strict_report.completed",
        phase=phase,
        mode=mode,
        path=str(target),
        counts=counts,
    )
    validations = gather_quality_validations(
        report_path=target,
        payload=payload,
        pythonwarnings=metadata.pythonwarnings,
    )
    report_text = build_quality_report(
        payload=payload,
        evidence=evidence,
        features=features,
        validations=validations,
    )
    print(report_text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
