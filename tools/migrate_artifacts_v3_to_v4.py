"""CLI tool to migrate GitHub Actions artifact steps from v3 to v4.

Usage examples::

    python tools/migrate_artifacts_v3_to_v4.py --dry-run
    python tools/migrate_artifacts_v3_to_v4.py --write
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, MutableMapping, Optional, Sequence, Tuple

import yaml
from yaml.representer import SafeRepresenter


yaml.add_representer(OrderedDict, SafeRepresenter.represent_dict)
yaml.SafeDumper.add_representer(OrderedDict, SafeRepresenter.represent_dict)


COMMENT_TEXT = "# NOTE: v4 download behavior may differ wrt root folder structure."
HELPER_STEP_NAME = "Inspect downloaded files (v4 migration helper)"
HELPER_STEP_IF = "always()"


@dataclass
class StepStats:
    uploads_updated: int = 0
    downloads_updated: int = 0
    names_added: int = 0
    helper_steps_added: int = 0
    comment_targets: set[Tuple[str, int]] | None = None

    def __post_init__(self) -> None:
        if self.comment_targets is None:
            self.comment_targets = set()

    def merge(self, other: "StepStats") -> None:
        self.uploads_updated += other.uploads_updated
        self.downloads_updated += other.downloads_updated
        self.names_added += other.names_added
        self.helper_steps_added += other.helper_steps_added
        if self.comment_targets is None:
            self.comment_targets = set()
        if other.comment_targets:
            self.comment_targets.update(other.comment_targets)

    @property
    def changed(self) -> bool:
        return any(
            [
                self.uploads_updated,
                self.downloads_updated,
                self.names_added,
                self.helper_steps_added,
                bool(self.comment_targets),
            ]
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upgrade actions/upload-artifact and actions/download-artifact from v3 to v4."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Print diffs without modifying files.")
    group.add_argument("--write", action="store_true", help="Apply changes in place (creates .bak backups).")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing .github/workflows/",
    )
    return parser.parse_args(argv)


def find_workflow_files(root: Path) -> List[Path]:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    return sorted(
        [
            *workflow_dir.rglob("*.yml"),
            *workflow_dir.rglob("*.yaml"),
        ],
        key=lambda p: str(p),
    )


def load_yaml_documents(text: str) -> List[object]:
    return list(yaml.safe_load_all(text))


def dump_yaml_documents(documents: Sequence[object]) -> str:
    dumped = yaml.safe_dump_all(documents, sort_keys=False)
    if not dumped.endswith("\n"):
        dumped += "\n"
    return dumped


def ensure_ordered_mapping(mapping: MutableMapping[str, object]) -> OrderedDict[str, object]:
    if isinstance(mapping, OrderedDict):
        return mapping
    ordered = OrderedDict()
    for key, value in mapping.items():
        ordered[key] = value
    return ordered


def ensure_with_mapping(step: MutableMapping[str, object]) -> OrderedDict[str, object]:
    current = step.get("with")
    if isinstance(current, MutableMapping):
        ordered = ensure_ordered_mapping(current)  # type: ignore[arg-type]
    else:
        ordered = OrderedDict()
    step["with"] = ordered
    return ordered


def normalize_path_entries(path_value: object) -> List[str]:
    def _extract(value: object) -> Iterable[str]:
        if isinstance(value, str):
            parts = [line.strip() for line in value.splitlines() if line.strip()]
            if parts:
                return parts
            return [value.strip()]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            result: List[str] = []
            for item in value:
                result.extend(_extract(item))
            return result
        return []

    entries = list(_extract(path_value))
    return [entry for entry in entries if entry]


def derive_artifact_name(path_value: object) -> Optional[str]:
    paths = normalize_path_entries(path_value)
    if not paths:
        return None

    def sanitize(component: str) -> str:
        cleaned = component.rstrip("/\\")
        if not cleaned:
            cleaned = component
        base = os.path.basename(cleaned) if cleaned else component
        if base in {"", ".", "*"}:
            parent = os.path.dirname(cleaned)
            if parent:
                base = os.path.basename(parent)
        base = base.strip()
        if not base:
            base = cleaned.strip()
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in base)
        safe = safe.strip("-_")
        return safe or "artifact"

    sanitized = [sanitize(path) for path in paths]
    joined = "-".join(sanitized)
    return joined or None


def upgrade_step(
    job_name: str,
    step_index: int,
    step: MutableMapping[str, object],
) -> StepStats:
    stats = StepStats()
    uses_value = step.get("uses")
    if not isinstance(uses_value, str):
        return stats

    is_upload = uses_value.startswith("actions/upload-artifact@v3")
    is_download = uses_value.startswith("actions/download-artifact@v3")

    if not (is_upload or is_download):
        return stats

    if is_upload:
        step["uses"] = "actions/upload-artifact@v4"
        stats.uploads_updated += 1
    if is_download:
        step["uses"] = "actions/download-artifact@v4"
        stats.downloads_updated += 1
        if stats.comment_targets is None:
            stats.comment_targets = set()
        stats.comment_targets.add((job_name, step_index))

    with_block = ensure_with_mapping(step)

    name_value = with_block.get("name")
    if not name_value:
        derived = derive_artifact_name(with_block.get("path"))
        if derived:
            new_with = OrderedDict()
            inserted = False
            for key, value in with_block.items():
                new_with[key] = value
                if key == "path":
                    new_with["name"] = derived
                    inserted = True
            if not inserted:
                new_with["name"] = derived
            step["with"] = new_with
            stats.names_added += 1
        else:
            step["with"] = with_block

    return stats


def process_steps(job_name: str, steps: List[MutableMapping[str, object]]) -> StepStats:
    stats = StepStats()
    index = 0
    while index < len(steps):
        step = steps[index]
        if not isinstance(step, MutableMapping):
            index += 1
            continue
        step_stats = upgrade_step(job_name, index, step)
        helper_added = False
        if step_stats.downloads_updated:
            if not has_helper_step(steps, index):
                helper_step = build_helper_step(step)
                steps.insert(index + 1, helper_step)
                step_stats.helper_steps_added += 1
                helper_added = True
        stats.merge(step_stats)
        index += 1
        if helper_added:
            index += 1
    return stats


def select_helper_path(step: MutableMapping[str, object]) -> str:
    with_block = step.get("with")
    if isinstance(with_block, MutableMapping):
        path_value = with_block.get("path")
        paths = normalize_path_entries(path_value)
        if paths:
            return paths[0]
    return "."


def build_helper_step(step: MutableMapping[str, object]) -> OrderedDict[str, object]:
    helper = OrderedDict()
    helper["name"] = HELPER_STEP_NAME
    helper["if"] = HELPER_STEP_IF
    helper["run"] = f"ls -R {select_helper_path(step)} || true"
    return helper


def has_helper_step(steps: Sequence[object], index: int) -> bool:
    next_index = index + 1
    if next_index >= len(steps):
        return False
    next_step = steps[next_index]
    if isinstance(next_step, MutableMapping):
        return next_step.get("name") == HELPER_STEP_NAME
    return False


def process_document(doc: object) -> StepStats:
    stats = StepStats()
    if not isinstance(doc, MutableMapping):
        return stats
    jobs = doc.get("jobs")
    if not isinstance(jobs, MutableMapping):
        return stats

    for job_name, job_config in jobs.items():
        if not isinstance(job_config, MutableMapping):
            continue
        steps = job_config.get("steps")
        if isinstance(steps, list):
            job_stats = process_steps(job_name=str(job_name), steps=steps)
            stats.merge(job_stats)
    return stats


def apply_comment_annotations(text: str, stats: StepStats) -> str:
    if not stats.comment_targets:
        return text

    targets_by_job: Dict[str, set[int]] = defaultdict(set)
    for (job_name, step_index) in stats.comment_targets:
        targets_by_job[job_name].add(step_index)

    lines = text.splitlines()
    output: List[str] = []
    jobs_indent = None
    current_job: Optional[str] = None
    job_indent = None
    steps_indent = None
    step_counters: Dict[str, int] = defaultdict(int)

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if stripped == "jobs:":
            jobs_indent = indent
            current_job = None
            job_indent = None
            steps_indent = None

        if (
            jobs_indent is not None
            and indent == jobs_indent + 2
            and stripped.endswith(":")
            and not stripped.startswith("- ")
        ):
            current_job = stripped[:-1].strip()
            job_indent = indent
            steps_indent = None
            step_counters[current_job] = 0

        if (
            current_job is not None
            and job_indent is not None
            and indent == job_indent + 2
            and stripped == "steps:"
        ):
            steps_indent = indent
            step_counters[current_job] = 0

        if (
            current_job is not None
            and steps_indent is not None
            and indent <= job_indent
            and stripped
            and not stripped.startswith("#")
        ):
            steps_indent = None

        if steps_indent is not None and stripped.startswith("- "):
            step_index = step_counters[current_job]
            step_counters[current_job] += 1
            if current_job in targets_by_job and step_index in targets_by_job[current_job]:
                comment_line = " " * indent + COMMENT_TEXT
                if not output or output[-1].strip() != COMMENT_TEXT:
                    output.append(comment_line)

        output.append(line)

    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def migrate_text(text: str) -> Tuple[str, StepStats]:
    documents = load_yaml_documents(text)
    aggregate_stats = StepStats()

    for doc in documents:
        doc_stats = process_document(doc)
        aggregate_stats.merge(doc_stats)

    dumped = dump_yaml_documents(documents)
    final_text = apply_comment_annotations(dumped, aggregate_stats)
    return final_text, aggregate_stats


def migrate_file(path: Path) -> Tuple[str, StepStats]:
    original_text = path.read_text()
    new_text, stats = migrate_text(original_text)
    return new_text, stats


def write_file_with_backup(path: Path, content: str) -> None:
    backup_path = Path(f"{path}.bak")
    backup_path.write_text(path.read_text())
    path.write_text(content)


def summarize(path: Path, stats: StepStats) -> str:
    parts = []
    if stats.uploads_updated:
        parts.append(f"upload:{stats.uploads_updated}")
    if stats.downloads_updated:
        parts.append(f"download:{stats.downloads_updated}")
    if stats.names_added:
        parts.append(f"names:{stats.names_added}")
    if stats.helper_steps_added:
        parts.append(f"helpers:{stats.helper_steps_added}")
    summary = ", ".join(parts) if parts else "no changes"
    return f"{path}: {summary}"


def contains_artifact_v3(text: str) -> bool:
    return bool(re.search(r"actions/(upload|download)-artifact@v3", text))


def run_migration(args: argparse.Namespace) -> int:
    files = find_workflow_files(args.root)
    if not files:
        print("No workflow files found.")
        return 0

    exit_code = 0
    for path in files:
        original = path.read_text()
        new_content, stats = migrate_text(original)
        if not stats.changed:
            print(f"{path}: no changes needed")
            continue
        if args.dry_run:
            diff = "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=str(path),
                    tofile=str(path),
                )
            )
            if diff:
                print(diff)
            print(summarize(path, stats))
        else:
            write_file_with_backup(path, new_content)
            print(summarize(path, stats))

    if args.write:
        remaining_v3 = []
        for path in files:
            if contains_artifact_v3(path.read_text()):
                remaining_v3.append(path)
        if remaining_v3:
            print("Remaining @v3 references detected:")
            for path in remaining_v3:
                print(f"  {path}")
            exit_code = 2

    return exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    return run_migration(args)


if __name__ == "__main__":
    raise SystemExit(main())
