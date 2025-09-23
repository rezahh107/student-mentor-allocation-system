#!/usr/bin/env python3
"""CLI tool to migrate GitHub Actions artifact steps from v3 to v4.

Usage examples::

    python tools/migrate_artifacts_v3_to_v4.py --dry-run
    python tools/migrate_artifacts_v3_to_v4.py --write

The tool scans ``.github/workflows`` for YAML workflow definitions and upgrades
any ``actions/upload-artifact@v3`` or ``actions/download-artifact@v3`` steps to
``@v4`` while preserving behaviour as much as possible."""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

NOTE_COMMENT_TEXT = (
    "# NOTE: GitHub Actions artifact v4 may alter folder structure compared to v3."
)
HELPER_STEP_NAME = "Inspect downloaded files (v4 migration helper)"


@dataclass
class StepChange:
    """Information about a migrated step."""

    was_upload: bool = False
    was_download: bool = False
    added_helper_step: bool = False
    ensured_name: bool = False


@dataclass
class FileMigrationResult:
    """Summary of per-file migration processing."""

    path: Path
    original_text: str
    new_text: str
    step_changes: List[StepChange] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.original_text != self.new_text


class TextEditor:
    """Accumulates textual replacements to apply to YAML content."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._changes: List[tuple[int, int, str]] = []

    @property
    def text(self) -> str:
        return self._text

    def replace_segment(self, start: int, end: int, new_text: str) -> None:
        """Replace the text between ``start`` and ``end`` with ``new_text``."""

        if start == end and not new_text:
            return
        self._changes.append((start, end, new_text))

    def insert(self, index: int, new_text: str) -> None:
        self.replace_segment(index, index, new_text)

    def apply(self) -> str:
        text = self._text
        for start, end, new_text in sorted(self._changes, key=lambda item: item[0], reverse=True):
            text = text[:start] + new_text + text[end:]
        return text


def find_workflow_files(base_dir: Path) -> List[Path]:
    """Return a sorted list of workflow files under ``.github/workflows``."""

    workflows_dir = base_dir / ".github" / "workflows"
    if not workflows_dir.exists():
        return []
    files: List[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        files.extend(workflows_dir.rglob(pattern))
    return sorted({path for path in files if path.is_file()})


def derive_name_from_path(path_value: object) -> str | None:
    """Derive a deterministic artifact name from a ``path`` value."""

    candidate: str | None = None
    if isinstance(path_value, str):
        candidate = path_value
    elif isinstance(path_value, list):
        for item in path_value:
            if isinstance(item, str) and item:
                candidate = item
                break
    if not candidate:
        return None
    candidate = candidate.rstrip("/")
    base = os.path.basename(candidate) if candidate else ""
    if not base or base in {".", ""}:
        base = "artifact"
    sanitized = base.replace(" ", "-") or "artifact"
    return sanitized


def node_to_basic(node: Node | None) -> object:
    """Convert a YAML node to basic Python structures."""

    if node is None:
        return None
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, SequenceNode):
        return [node_to_basic(child) for child in node.value]
    if isinstance(node, MappingNode):
        result = {}
        for key_node, value_node in node.value:
            key = node_to_basic(key_node)
            result[key] = node_to_basic(value_node)
        return result
    return None


def find_mapping_entry(mapping: MappingNode, key: str) -> tuple[ScalarNode, Node] | None:
    """Return the (key_node, value_node) pair for ``key`` within ``mapping``."""

    for key_node, value_node in mapping.value:
        if isinstance(key_node, ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def node_contains(node: Node, needle: str) -> bool:
    """Recursively determine whether ``needle`` appears in a node's scalar values."""

    if isinstance(node, ScalarNode):
        return needle in node.value
    if isinstance(node, SequenceNode):
        return any(node_contains(child, needle) for child in node.value)
    if isinstance(node, MappingNode):
        return any(node_contains(child, needle) for _, child in node.value)
    return False


def step_has_name(step_node: MappingNode, name: str) -> bool:
    entry = find_mapping_entry(step_node, "name")
    return bool(
        entry
        and isinstance(entry[1], ScalarNode)
        and entry[1].value == name
    )


def line_start_index(text: str, index: int) -> int:
    prev_newline = text.rfind("\n", 0, index)
    return prev_newline + 1 if prev_newline != -1 else 0


def has_preceding_comment(text: str, index: int) -> bool:
    cursor = index
    while cursor > 0:
        prev_newline = text.rfind("\n", 0, cursor - 1)
        line_start = prev_newline + 1 if prev_newline != -1 else 0
        line = text[line_start:cursor].strip()
        if not line:
            cursor = prev_newline
            if cursor == -1:
                break
            continue
        return line == NOTE_COMMENT_TEXT
    return False


def replace_uses(editor: TextEditor, text: str, node: ScalarNode, old: str, new: str) -> None:
    start = node.start_mark.index
    end = node.end_mark.index
    segment = text[start:end]
    updated = segment.replace(old, new)
    if segment != updated:
        editor.replace_segment(start, end, updated)


def ensure_name_in_with(
    editor: TextEditor,
    text: str,
    with_key: ScalarNode,
    with_node: MappingNode,
    derived_name: str,
) -> None:
    if not derived_name:
        return
    if find_mapping_entry(with_node, "name"):
        return

    path_entry = find_mapping_entry(with_node, "path")
    base_indent = with_key.start_mark.column + 2
    indent_column = path_entry[0].start_mark.column if path_entry else base_indent
    indent = " " * indent_column

    if getattr(with_node, "flow_style", None):
        indent_column = base_indent
        insert_lines: list[str] = []
        name_inserted = False
        for key_node, value_node in with_node.value:
            key_text = text[key_node.start_mark.index:key_node.end_mark.index]
            value_text = text[value_node.start_mark.index:value_node.end_mark.index]
            insert_lines.append(f"{indent}{key_text}: {value_text}")
            if key_node.value == "path":
                insert_lines.append(f"{indent}name: {derived_name}")
                name_inserted = True
        if not name_inserted:
            insert_lines.append(f"{indent}name: {derived_name}")
        replacement = "\n" + "\n".join(insert_lines)
        editor.replace_segment(with_node.start_mark.index, with_node.end_mark.index, replacement)
        return

    insert_index = (
        path_entry[1].end_mark.index if path_entry else with_node.end_mark.index
    )
    editor.insert(insert_index, f"\n{indent}name: {derived_name}")


def insert_comment(editor: TextEditor, text: str, step_node: MappingNode) -> None:
    step_start = step_node.start_mark.index
    line_start = line_start_index(text, step_start)
    if has_preceding_comment(text, line_start):
        return
    indent = " " * step_node.start_mark.column
    editor.insert(line_start, f"{indent}{NOTE_COMMENT_TEXT}\n")


def insert_helper_step(
    editor: TextEditor,
    text: str,
    steps_node: SequenceNode,
    step_index: int,
    step_node: MappingNode,
    normalized_path: str,
) -> bool:
    helper_exists = any(
        isinstance(node, MappingNode) and step_has_name(node, HELPER_STEP_NAME)
        for node in steps_node.value[step_index + 1 :]
    )
    if helper_exists:
        return False
    token = normalized_path.rstrip("/") + "/"
    has_reference = any(
        isinstance(node, MappingNode) and node_contains(node, token)
        for node in steps_node.value[step_index + 1 :]
    )
    if not has_reference:
        return False
    indent = " " * step_node.start_mark.column
    helper_lines = [
        f"{indent}- name: {HELPER_STEP_NAME}",
        f"{indent}  if: always()",
        f"{indent}  run: ls -R {normalized_path} || true",
    ]
    insertion = "\n".join(helper_lines)
    if not insertion.endswith("\n"):
        insertion += "\n"
    editor.insert(step_node.end_mark.index, insertion)
    return True


def process_steps(
    steps_node: SequenceNode,
    editor: TextEditor,
    text: str,
) -> List[StepChange]:
    changes: List[StepChange] = []
    for idx, step in enumerate(steps_node.value):
        if not isinstance(step, MappingNode):
            continue
        uses_entry = find_mapping_entry(step, "uses")
        if not uses_entry or not isinstance(uses_entry[1], ScalarNode):
            continue
        uses_value = uses_entry[1].value
        change = StepChange()
        if "actions/upload-artifact@v3" in uses_value:
            replace_uses(editor, text, uses_entry[1], "actions/upload-artifact@v3", "actions/upload-artifact@v4")
            change.was_upload = True
        elif "actions/download-artifact@v3" in uses_value:
            replace_uses(editor, text, uses_entry[1], "actions/download-artifact@v3", "actions/download-artifact@v4")
            change.was_download = True
            insert_comment(editor, text, step)
        else:
            continue

        with_entry = find_mapping_entry(step, "with")
        if with_entry and isinstance(with_entry[1], MappingNode):
            path_entry = find_mapping_entry(with_entry[1], "path")
            path_value = node_to_basic(path_entry[1]) if path_entry else None
            derived_name = derive_name_from_path(path_value)
            ensure_name_in_with(editor, text, with_entry[0], with_entry[1], derived_name or "")
            if derived_name and not find_mapping_entry(with_entry[1], "name"):
                change.ensured_name = True
            if change.was_download and isinstance(path_value, str) and path_value.strip():
                normalized = path_value.rstrip("/") or path_value
                if insert_helper_step(editor, text, steps_node, idx, step, normalized):
                    change.added_helper_step = True
        changes.append(change)
    return changes


def walk_nodes(node: Node, editor: TextEditor, text: str) -> List[StepChange]:
    changes: List[StepChange] = []
    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode) and key_node.value == "steps" and isinstance(value_node, SequenceNode):
                changes.extend(process_steps(value_node, editor, text))
            else:
                changes.extend(walk_nodes(value_node, editor, text))
    elif isinstance(node, SequenceNode):
        for child in node.value:
            changes.extend(walk_nodes(child, editor, text))
    return changes


def migrate_file(path: Path) -> FileMigrationResult:
    original_text = path.read_text(encoding="utf-8")
    editor = TextEditor(original_text)
    documents = [doc for doc in yaml.compose_all(original_text) if doc is not None]
    step_changes: List[StepChange] = []
    for document in documents:
        step_changes.extend(walk_nodes(document, editor, original_text))
    new_text = editor.apply()
    if original_text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    return FileMigrationResult(path=path, original_text=original_text, new_text=new_text, step_changes=step_changes)


def apply_migrations(results: Sequence[FileMigrationResult], write: bool) -> int:
    exit_code = 0
    for result in results:
        if not result.changed:
            print(f"{result.path}: no changes needed")
            continue
        diff = "".join(
            difflib.unified_diff(
                result.original_text.splitlines(keepends=True),
                result.new_text.splitlines(keepends=True),
                fromfile=str(result.path),
                tofile=f"{result.path} (migrated)",
            )
        )
        if write:
            backup_path = result.path.with_suffix(result.path.suffix + ".bak")
            shutil.copy2(result.path, backup_path)
            result.path.write_text(result.new_text, encoding="utf-8")
            print(f"{result.path}: migrated (backup at {backup_path.name})")
        else:
            print(f"{result.path}: would migrate")
            print(diff)
    if write:
        remaining = [
            r
            for r in results
            if (
                "actions/upload-artifact@v3" in r.new_text
                or "actions/download-artifact@v3" in r.new_text
            )
        ]
        if remaining:
            exit_code = 2
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="show diff without writing")
    mode.add_argument("--write", action="store_true", help="apply changes in place")
    parser.add_argument(
        "--base-dir",
        default=Path.cwd(),
        type=Path,
        help="repository root containing .github/workflows",
    )
    args = parser.parse_args(argv)

    base_dir: Path = args.base_dir
    workflow_files = find_workflow_files(base_dir)
    if not workflow_files:
        print("No workflow files found; nothing to do.")
        return 0

    results = [migrate_file(path) for path in workflow_files]
    any_changes = any(result.changed for result in results)
    if args.dry_run and not any_changes:
        print("All workflows already migrated.")
        return 0
    exit_code = apply_migrations(results, write=args.write)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
