#!/usr/bin/env python3
"""Patch GitHub Actions workflows to enforce the CI pytest runner."""
from __future__ import annotations

import argparse
import difflib
import os
import random
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

RUNNER_COMMAND = (
    "python tools/ci_pytest_runner.py --mode ${{ matrix.mode }} --flush-redis auto "
    "--probe-mw-order auto --p95-samples 5"
)

MATRIX_MODES = ["stub", "redis"]

RUNNER_STEP_SUFFIX = " (via CI runner)"
INSTALL_STEP_NAME = "Install dependencies (with extras)"
SELECT_STEP_NAME = "Select mode env"

PYTEST_WORD_RE = re.compile(r"(?i)\bpytest\b")


class PatchError(RuntimeError):
    """Domain specific error for workflow patching."""


def _persian_error(code: str, message: str) -> PatchError:
    return PatchError(f"{code}: {message}")


@dataclass
class WorkflowSelection:
    path: Path
    job_id: str


def _load_ruamel():
    try:
        from ruamel.yaml import YAML  # type: ignore
        from ruamel.yaml.comments import CommentedMap  # type: ignore

        return YAML, CommentedMap
    except Exception:  # pragma: no cover - optional dependency
        return None, None


def _ensure_runner_exists(root: Path) -> None:
    runner = root / "tools" / "ci_pytest_runner.py"
    if not runner.exists():
        raise _persian_error(
            "RUNNER_MISSING",
            "فایل tools/ci_pytest_runner.py موجود نیست؛ ابتدا آن را اضافه کنید",
        )


def _find_workflow(root: Path, specific: Optional[str]) -> WorkflowSelection:
    candidates: Iterable[Path]
    if specific:
        target = (root / specific).resolve()
        if not target.exists():
            raise _persian_error("WF_NOT_FOUND", f"فایل {target} پیدا نشد")
        candidates = [target]
    else:
        workflow_root = root / ".github" / "workflows"
        if not workflow_root.exists():
            raise _persian_error(
                "WF_NOT_FOUND",
                "هیچ فایل ورک‌فلو پیدا نشد؛ لطفاً پوشه .github/workflows را بررسی کنید",
            )
        candidates = sorted(workflow_root.glob("*.yml"))

    runner_detected = False
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        if RUNNER_COMMAND in text:
            runner_detected = True
        if _text_contains_pytest(text):
            job_id = _find_job_id(text)
            return WorkflowSelection(candidate, job_id or "")

    if runner_detected:
        raise _persian_error(
            "PATCH_IDEMPOTENT",
            "گردش‌کار قبلاً با رانر CI به‌روزرسانی شده است",
        )

    raise _persian_error(
        "PATCH_ANCHOR_NOT_FOUND",
        "هیچ مرحلهٔ pytest برای جایگزینی یافت نشد؛ فایل هدف را مشخص کنید",
    )


def _find_job_id(text: str) -> Optional[str]:
    job_regex = re.compile(r"^(\s{2,})([A-Za-z0-9_-]+):\s*$", re.MULTILINE)
    matches = list(job_regex.finditer(text))
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        segment = text[start:end]
        if "steps:" in segment and "run:" in segment and "pytest" in segment:
            return match.group(2)
    return None


def _create_install_step(commented_map_cls=None):
    payload = {
        "name": INSTALL_STEP_NAME,
        "run": (
            "python -m pip install --upgrade pip\n"
            "pip install -e \".[fastapi,redis,dev]\" || true\n"
            "pip install fastapi redis pytest-asyncio uvicorn httpx pytest prometheus-client"
        ),
    }
    if commented_map_cls:
        node = commented_map_cls()
        node.update(payload)
        return node
    return payload


def _create_select_step(commented_map_cls=None):
    payload = {
        "name": SELECT_STEP_NAME,
        "run": (
            "if [ \"${{ matrix.mode }}\" = \"stub\" ]; then\n"
            "  echo \"TEST_REDIS_STUB=1\" >> $GITHUB_ENV\n"
            "else\n"
            "  echo \"PYTEST_REDIS=1\" >> $GITHUB_ENV\n"
            "fi"
        ),
    }
    if commented_map_cls:
        node = commented_map_cls()
        node.update(payload)
        return node
    return payload


def _normalize_modes(modes: Sequence[str]) -> Sequence[str]:
    return list(modes)


def _append_suffix(line: str) -> str:
    indent_length = len(line) - len(line.lstrip(" "))
    indent = line[:indent_length]
    stripped = line[indent_length:]

    match = re.match(r"(?P<header>(?:-\s*)?name:)(?P<tail>.*)", stripped)
    if not match:
        return line

    header = match.group("header")
    tail = match.group("tail")

    leading_ws_length = len(tail) - len(tail.lstrip(" "))
    leading_ws = tail[:leading_ws_length]
    remainder = tail[leading_ws_length:]

    tail_match = re.match(
        r"(?P<name>.*?)(?P<anchor>\s*&[^\s#]+)?(?P<comment>\s+#.*)?$",
        remainder,
    )
    if not tail_match:
        if remainder.strip().endswith(RUNNER_STEP_SUFFIX):
            return line
        updated = f"{indent}{header}{tail.rstrip()}{RUNNER_STEP_SUFFIX}"
        return updated

    raw_name = tail_match.group("name") or ""
    anchor_part = tail_match.group("anchor") or ""
    comment_part = tail_match.group("comment") or ""
    name_core = raw_name.rstrip()
    trailing = raw_name[len(name_core) :]

    if not name_core:
        return line

    new_core = name_core
    if name_core.startswith(("'", '"')) and len(name_core) >= 2 and name_core.endswith(name_core[0]):
        quote = name_core[0]
        inner = name_core[1:-1]
        if inner.endswith(RUNNER_STEP_SUFFIX):
            return line
        new_core = f"{quote}{inner}{RUNNER_STEP_SUFFIX}{quote}"
    else:
        if name_core.endswith(RUNNER_STEP_SUFFIX):
            return line
        new_core = f"{name_core}{RUNNER_STEP_SUFFIX}"

    final_name = f"{new_core}{trailing}"
    return f"{indent}{header}{leading_ws}{final_name}{anchor_part}{comment_part}"


def _split_indent(line: str) -> tuple[int, str]:
    stripped = line.lstrip(" \t")
    return len(line) - len(stripped), stripped


def _line_has_pytest(text: str) -> bool:
    lower = text.lower()
    if "pytest" not in lower:
        return False
    if "pip install" in lower or "pip3 install" in lower:
        return False
    if "pipenv install" in lower:
        return False
    return bool(PYTEST_WORD_RE.search(text))


@dataclass
class StepBlock:
    start: int
    end: int
    indent: int
    lines: list[str]

    def contains_pytest(self) -> bool:
        run_indent = None
        for line in self.lines:
            indent, stripped = _split_indent(line)
            if stripped.startswith("run:"):
                run_indent = indent
                if _line_has_pytest(stripped):
                    return True
            elif run_indent is not None and indent > run_indent:
                if _line_has_pytest(stripped):
                    return True
            else:
                run_indent = None
        return False

    def name(self) -> Optional[str]:
        for line in self.lines:
            _, stripped = _split_indent(line)
            if stripped.startswith("name:"):
                return stripped.split(":", 1)[1].strip()
        return None


def _text_contains_pytest(text: str) -> bool:
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        indent, stripped = _split_indent(line)
        if stripped.startswith("-"):
            end = idx + 1
            while end < len(lines):
                current = lines[end]
                cur_indent, cur_stripped = _split_indent(current)
                if not cur_stripped:
                    end += 1
                    continue
                if cur_indent < indent:
                    break
                if cur_indent == indent and cur_stripped.startswith("-"):
                    break
                end += 1
            block = StepBlock(idx, end, indent, lines[idx:end])
            if block.contains_pytest():
                return True
            idx = end
        else:
            idx += 1
    return False


class TextWorkflowPatcher:
    def __init__(self, text: str) -> None:
        self.original = text
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self._newline_len = len(self.newline)
        self.lines = text.splitlines()
        self.changed = False
        self.debug: dict[str, str] = {
            "matrix_action": "unknown",
            "mode_writer": "text",
        }
        self._job_range_keys: dict[int, str] = {}
        self._offset_cache: list[int] = []
        self._offset_valid = False
        self._rebuild_offsets()

    def patch(self) -> str:
        matrix_done: set[str] = set()
        support_done: set[str] = set()
        processed_any = False
        search_index = 0
        while True:
            block = self._next_pytest_block(search_index)
            if block is None:
                break
            processed_any = True
            job_bounds = self._locate_job_bounds(block.start)
            job_key = self._job_key(job_bounds)
            if job_key not in matrix_done:
                self._ensure_matrix(job_bounds)
                matrix_done.add(job_key)
                block = self._next_pytest_block(job_bounds[0])
                if block is None:
                    raise _persian_error(
                        "PATCH_ANCHOR_NOT_FOUND",
                        "پس از افزودن ماتریس، گام pytest پیدا نشد",
                    )
                job_bounds = self._locate_job_bounds(block.start)
            if job_key not in support_done:
                new_start = self._ensure_support_steps(job_bounds, block)
                support_done.add(job_key)
                block = self._extract_step(new_start)
                if block is None or not block.contains_pytest():
                    block = self._next_pytest_block(job_bounds[0])
                    if block is None:
                        raise _persian_error(
                            "PATCH_ANCHOR_NOT_FOUND",
                            "پس از درج مراحل پشتیبان، گام pytest یافت نشد",
                        )
                job_bounds = self._locate_job_bounds(block.start)
            self.debug["step_start"] = str(block.start)
            updated_step = self._rewrite_step(block)
            self.lines[block.start:block.end] = updated_step
            self._invalidate_offsets()
            self.debug["step_after"] = str(block.start)
            search_index = block.start + len(updated_step)
        if not processed_any:
            raise _persian_error(
                "PATCH_ANCHOR_NOT_FOUND",
                "هیچ مرحلهٔ pytest برای جایگزینی یافت نشد (متن)",
            )
        return self.newline.join(self.lines)

    def _next_pytest_block(self, start: int) -> Optional[StepBlock]:
        idx = start
        while idx < len(self.lines):
            block = self._extract_step(idx)
            if block is None:
                idx += 1
                continue
            if block.contains_pytest():
                return block
            idx = block.end
        return None

    def _extract_step(self, index: int) -> Optional[StepBlock]:
        if index >= len(self.lines):
            return None
        line = self.lines[index]
        indent, stripped = _split_indent(line)
        if not stripped.startswith("-"):
            return None
        end = self._step_end(index, indent)
        return StepBlock(index, end, indent, self.lines[index:end])

    def _step_end(self, start: int, indent: int) -> int:
        idx = start + 1
        while idx < len(self.lines):
            current = self.lines[idx]
            if not current.strip():
                idx += 1
                continue
            cur_indent, stripped = _split_indent(current)
            if cur_indent < indent:
                break
            if cur_indent == indent and stripped.startswith("-"):
                break
            idx += 1
        return idx

    def _job_key(self, job_bounds: tuple[int, int]) -> str:
        job_start, job_end = job_bounds
        if job_start in self._job_range_keys:
            key = self._job_range_keys[job_start]
        else:
            start_offset = self._byte_offset(job_start)
            end_offset = self._byte_offset(job_end)
            key = f"بازه:{start_offset}-{end_offset}"
            self._job_range_keys[job_start] = key
        self.debug["job_range"] = key
        return key

    def _locate_job_bounds(self, index: int) -> tuple[int, int]:
        steps_line = None
        for idx in range(index, -1, -1):
            indent, stripped = _split_indent(self.lines[idx])
            if stripped.startswith("steps:"):
                steps_line = idx
                steps_indent = indent
                break
        if steps_line is None:
            raise _persian_error("PATCH_ANCHOR_NOT_FOUND", "بلاک steps پیدا نشد")

        job_start = None
        for idx in range(steps_line - 1, -1, -1):
            indent, stripped = _split_indent(self.lines[idx])
            if indent < steps_indent and stripped.endswith(":") and not stripped.startswith("-"):
                job_start = idx
                job_indent = indent
                break
        if job_start is None:
            raise _persian_error("PATCH_ANCHOR_NOT_FOUND", "job متناظر یافت نشد")

        job_end = len(self.lines)
        for idx in range(job_start + 1, len(self.lines)):
            indent, stripped = _split_indent(self.lines[idx])
            if stripped and indent <= job_indent:
                job_end = idx
                break
        return job_start, job_end

    def _ensure_matrix(self, job_bounds: tuple[int, int]) -> None:
        job_start, job_end = job_bounds
        job_indent, _ = _split_indent(self.lines[job_start])
        strategy_idx = None
        strategy_indent = None
        matrix_idx = None
        matrix_indent = None
        mode_idx = None
        mode_indent = None
        for idx in range(job_start + 1, job_end):
            indent, stripped = _split_indent(self.lines[idx])
            if not stripped:
                continue
            if indent <= job_indent:
                break
            if stripped.startswith("strategy:"):
                strategy_idx = idx
                strategy_indent = indent
                continue
            if strategy_idx is not None and indent <= strategy_indent:
                break
            if strategy_idx is not None:
                if stripped.startswith("matrix:") and indent > strategy_indent:
                    matrix_idx = idx
                    matrix_indent = indent
                    continue
                if matrix_idx is not None:
                    if stripped.startswith("mode:") and indent > (matrix_indent or 0):
                        mode_idx = idx
                        mode_indent = indent
                        break
                    if indent <= matrix_indent:
                        break
        if mode_idx is not None:
            line = self.lines[mode_idx]
            _, stripped_line = _split_indent(line)
            if stripped_line.strip() == "mode:":
                values: list[str] = []
                idx = mode_idx + 1
                while idx < len(self.lines):
                    item_line = self.lines[idx]
                    item_indent, item_stripped = _split_indent(item_line)
                    if not item_stripped:
                        idx += 1
                        continue
                    if item_indent <= (mode_indent or 0):
                        break
                    if item_stripped.startswith("- "):
                        values.append(item_stripped[2:].strip().strip("'\""))
                    idx += 1
                if values == MATRIX_MODES:
                    self.debug["matrix_action"] = "existing"
                    return
            else:
                existing = stripped_line.split(":", 1)[1].strip()
                normalized = existing.strip("[] ")
                parts = [part.strip() for part in normalized.split(",") if part.strip()]
                if [p.strip("'\"") for p in parts] == MATRIX_MODES:
                    self.debug["matrix_action"] = "existing"
                    return
            raise _persian_error(
                "PATCH_CONFLICT_MATRIX",
                "محور mode از قبل وجود دارد ولی مقادیر آن ناسازگار است",
            )
            return

        if strategy_idx is None:
            steps_idx = self._find_steps_index(job_start, job_end)
            insert_at = steps_idx if steps_idx is not None else job_start + 1
            strategy_indent = job_indent + 2
            matrix_indent = strategy_indent + 2
            mode_indent = matrix_indent + 2
            block = [
                " " * strategy_indent + "strategy:",
                " " * matrix_indent + "matrix:",
                " " * mode_indent + "mode: [stub, redis]",
            ]
            self.lines[insert_at:insert_at] = block
            self._invalidate_offsets()
            self.changed = True
            self.debug["matrix_action"] = "strategy_created"
            return
        if matrix_idx is None:
            matrix_indent = (strategy_indent or 0) + 2
            insert_at = strategy_idx + 1
            block = [
                " " * matrix_indent + "matrix:",
                " " * (matrix_indent + 2) + "mode: [stub, redis]",
            ]
            self.lines[insert_at:insert_at] = block
            self._invalidate_offsets()
            self.changed = True
            self.debug["matrix_action"] = "matrix_created"
            return

        mode_indent = (matrix_indent or 0) + 2
        insert_at = matrix_idx + 1
        self.lines.insert(insert_at, " " * mode_indent + "mode: [stub, redis]")
        self._invalidate_offsets()
        self.changed = True
        self.debug["matrix_action"] = "mode_added"

    def _find_steps_index(self, job_start: int, job_end: int) -> Optional[int]:
        for idx in range(job_start + 1, job_end):
            _, stripped = _split_indent(self.lines[idx])
            if stripped.startswith("steps:"):
                return idx
        return None

    def _collect_step_names(self, job_bounds: tuple[int, int]) -> set[str]:
        job_start, job_end = job_bounds
        names: set[str] = set()
        idx = job_start
        while idx < job_end:
            block = self._extract_step(idx)
            if block is None:
                idx += 1
                continue
            name = self._block_name(block)
            if name:
                names.add(name)
            idx = block.end
        return names

    def _build_install_block(self, indent: str) -> list[str]:
        return [
            f"{indent}- name: {INSTALL_STEP_NAME}",
            f"{indent}  run: |",
            f"{indent}    python -m pip install --upgrade pip",
            f"{indent}    pip install -e \".[fastapi,redis,dev]\" || true",
            f"{indent}    pip install fastapi redis pytest-asyncio uvicorn httpx pytest prometheus-client",
        ]

    def _build_select_block(self, indent: str) -> list[str]:
        return [
            f"{indent}- name: {SELECT_STEP_NAME}",
            f"{indent}  run: |",
            f"{indent}    if [ \"${{{{ matrix.mode }}}}\" = \"stub\" ]; then",
            f"{indent}      echo \"TEST_REDIS_STUB=1\" >> $GITHUB_ENV",
            f"{indent}    else",
            f"{indent}      echo \"PYTEST_REDIS=1\" >> $GITHUB_ENV",
            f"{indent}    fi",
        ]

    def _ensure_support_steps(self, job_bounds: tuple[int, int], step: StepBlock) -> int:
        names = self._collect_step_names(job_bounds)
        indent_str = " " * step.indent
        inserts: list[str] = []
        if INSTALL_STEP_NAME not in names:
            inserts.extend(self._build_install_block(indent_str))
        if SELECT_STEP_NAME not in names:
            inserts.extend(self._build_select_block(indent_str))
        if not inserts:
            self.debug.setdefault("support_steps", "existing")
            return step.start
        self.lines[step.start:step.start] = inserts
        self._invalidate_offsets()
        self.changed = True
        self.debug["support_steps"] = "inserted"
        return step.start + len(inserts)

    def _invalidate_offsets(self) -> None:
        self._offset_valid = False

    def _ensure_offsets(self) -> None:
        if not self._offset_valid:
            self._rebuild_offsets()

    def _rebuild_offsets(self) -> None:
        offsets = [0]
        running = 0
        newline_len = self._newline_len
        for line in self.lines:
            running += len(line)
            running += newline_len
            offsets.append(running)
        self._offset_cache = offsets
        self._offset_valid = True

    def _byte_offset(self, line_index: int) -> int:
        self._ensure_offsets()
        if not self._offset_cache:
            return 0
        max_index = len(self._offset_cache) - 1
        if line_index <= max_index:
            return self._offset_cache[line_index]
        extra = max(0, line_index - max_index) * self._newline_len
        return self._offset_cache[-1] + extra

    @staticmethod
    def _block_name(block: StepBlock) -> Optional[str]:
        for line in block.lines:
            stripped = line.lstrip()
            match = re.match(r"(?:-\s*)?name:\s*(.*)", stripped)
            if not match:
                continue
            value = match.group(1)
            value = re.split(r"\s+#", value, 1)[0]
            value = re.split(r"\s*&", value, 1)[0]
            cleaned = value.strip()
            if cleaned.startswith(("'", '"')) and len(cleaned) >= 2 and cleaned.endswith(cleaned[0]):
                cleaned = cleaned[1:-1]
            return cleaned
        return None

    def _rewrite_step(self, step: StepBlock) -> list[str]:
        indent_str = " " * step.indent
        result: list[str] = []
        i = 0
        name_seen = False
        run_index_hint: Optional[int] = None
        while i < len(step.lines):
            line = step.lines[i]
            indent, stripped = _split_indent(line)
            if stripped.startswith("name:") or stripped.startswith("- name:"):
                name_seen = True
                new_line = _append_suffix(line)
                if new_line != line:
                    self.changed = True
                result.append(new_line)
                i += 1
                continue
            if stripped.startswith("env:"):
                env_indent = indent
                result.append(line)
                i += 1
                while i < len(step.lines):
                    next_line = step.lines[i]
                    n_indent, _ = _split_indent(next_line)
                    if next_line.strip() == "":
                        result.append(next_line)
                        i += 1
                        continue
                    if n_indent <= env_indent:
                        break
                    result.append(next_line)
                    i += 1
                continue
            if stripped.startswith("run:"):
                run_indent = indent
                run_index_hint = len(result)
                i += 1
                while i < len(step.lines):
                    next_line = step.lines[i]
                    n_indent, _ = _split_indent(next_line)
                    if next_line.strip() == "":
                        i += 1
                        continue
                    if n_indent <= run_indent:
                        break
                    i += 1
                result.extend(
                    [
                        f"{indent_str}  run: |",
                        f"{indent_str}    {RUNNER_COMMAND}",
                    ]
                )
                self.changed = True
                continue
            result.append(line)
            i += 1

        if not name_seen:
            result.insert(0, f"{indent_str}- name: Run pytest suite{RUNNER_STEP_SUFFIX}")
        return self._ensure_env_block(result, step.indent, run_index_hint)

    def _ensure_env_block(
        self, lines: list[str], step_indent: int, run_index_hint: Optional[int]
    ) -> list[str]:
        env_idx = None
        env_indent = None
        for idx, line in enumerate(lines):
            indent, stripped = _split_indent(line)
            if stripped.startswith("env:"):
                env_idx = idx
                env_indent = indent
                break
        if env_idx is None:
            env_indent = step_indent + 2
            insert_at = run_index_hint if run_index_hint is not None else len(lines)
            env_lines = [
                " " * env_indent + "env:",
                " " * (env_indent + 2) + "PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'",
            ]
            lines[insert_at:insert_at] = env_lines
            self.changed = True
            self.debug["env_action"] = "created"
            return lines

        assert env_indent is not None
        insert_at = env_idx + 1
        idx = env_idx + 1
        found = False
        while idx < len(lines):
            current = lines[idx]
            indent, stripped = _split_indent(current)
            if not stripped:
                idx += 1
                insert_at = idx
                continue
            if indent <= env_indent:
                break
            if "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in stripped:
                found = True
                break
            insert_at = idx + 1
            idx += 1
        if not found:
            lines.insert(insert_at, " " * (env_indent + 2) + "PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'")
            self.changed = True
            self.debug["env_action"] = "augmented"
        else:
            self.debug.setdefault("env_action", "present")
        return lines


class RuamelWorkflowPatcher:
    def __init__(self, source_text: str, data, comment_cls) -> None:
        self._source_text = source_text
        self.data = data
        self.comment_cls = comment_cls
        self.changed = False
        self.debug: dict[str, str] = {"mode_writer": "ruamel", "reordered_ruamel": "false"}
        self._job_offset_map = self._build_job_offset_map(source_text)

    def patch(self) -> bool:
        if not isinstance(self.data, dict):
            raise _persian_error("PATCH_ANCHOR_NOT_FOUND", "ساختار YAML معتبر نیست")
        jobs = self.data.get("jobs")
        if not isinstance(jobs, dict):
            raise _persian_error("PATCH_ANCHOR_NOT_FOUND", "jobs در فایل یافت نشد")
        found_any = False
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            matrix_done = False
            support_done = False
            idx = 0
            while idx < len(steps):
                step = steps[idx]
                if not isinstance(step, dict):
                    idx += 1
                    continue
                if self._step_has_pytest(step):
                    found_any = True
                    self.debug["step_index"] = str(idx)
                    offsets = self._job_offset_map.get(job_name)
                    if offsets:
                        self.debug["job_range"] = f"بازه:{offsets[0]}-{offsets[1]}"
                    else:
                        self.debug["job_range"] = f"ruamel-job:{job_name}"
                    if not matrix_done:
                        self._ensure_matrix(job)
                        matrix_done = True
                    if not support_done:
                        inserted = self._ensure_support_steps(job, idx)
                        support_done = True
                        if inserted:
                            idx += inserted
                            continue
                    self._rewrite_step(job, idx)
                idx += 1
        if not found_any:
            raise _persian_error(
                "PATCH_ANCHOR_NOT_FOUND",
                "هیچ مرحلهٔ pytest برای جایگزینی یافت نشد (ruamel)",
            )
        return self.changed

    def _step_has_pytest(self, step: dict) -> bool:
        run = step.get("run")
        if isinstance(run, str):
            return any(_line_has_pytest(part) for part in run.splitlines())
        return False

    def _ensure_matrix(self, job: dict) -> None:
        strategy = job.setdefault("strategy", self.comment_cls() if self.comment_cls else {})
        if not isinstance(strategy, dict):
            raise _persian_error("PATCH_ANCHOR_NOT_FOUND", "strategy ساختار غیرمنتظره دارد")
        matrix = strategy.get("matrix")
        if matrix is None:
            matrix = self.comment_cls() if self.comment_cls else {}
            strategy["matrix"] = matrix
            matrix["mode"] = list(MATRIX_MODES)
            self.changed = True
            self.debug["matrix_action"] = "strategy_created"
            return
        if not isinstance(matrix, dict):
            raise _persian_error("PATCH_ANCHOR_NOT_FOUND", "matrix ساختار غیرمنتظره دارد")
        modes = matrix.get("mode")
        if modes is None:
            matrix["mode"] = list(MATRIX_MODES)
            self.changed = True
            self.debug["matrix_action"] = "mode_added"
            return
        normalized = _normalize_modes(modes)
        if list(normalized) == MATRIX_MODES:
            self.debug["matrix_action"] = "existing"
            return
        raise _persian_error(
            "PATCH_CONFLICT_MATRIX",
            "محور mode از قبل وجود دارد ولی مقادیر آن ناسازگار است",
        )

    def _ensure_support_steps(self, job: dict, target_index: int) -> int:
        steps = job.get("steps")
        assert isinstance(steps, list)
        runner_step = steps[target_index]
        desired_names = [INSTALL_STEP_NAME, SELECT_STEP_NAME]

        occurrences: dict[str, list[int]] = {name: [] for name in desired_names}
        for idx, raw_step in enumerate(steps):
            if idx == target_index or not isinstance(raw_step, dict):
                continue
            normalized = self._normalize_name(raw_step.get("name"))
            if normalized in occurrences:
                occurrences[normalized].append(idx)

        duplicates = any(len(indices) > 1 for indices in occurrences.values())
        after_runner = any(any(idx > target_index for idx in indices) for indices in occurrences.values())
        missing = any(len(indices) == 0 for indices in occurrences.values())

        def _current_order_ok() -> bool:
            start = target_index - len(desired_names)
            if start < 0:
                return False
            for offset, expected in enumerate(desired_names):
                idx = start + offset
                if idx < 0 or idx >= len(steps):
                    return False
                step_obj = steps[idx]
                if not isinstance(step_obj, dict):
                    return False
                if self._normalize_name(step_obj.get("name")) != expected:
                    return False
            return True

        order_ok = _current_order_ok()
        need_reorder = duplicates or after_runner or missing or not order_ok

        desired_steps: list[dict] = []
        original_indices: dict[str, str] = {}
        for name in desired_names:
            if occurrences[name]:
                first_idx = occurrences[name][0]
                original_indices[name] = str(first_idx)
                desired_steps.append(steps[first_idx])
            else:
                original_indices[name] = "جدید"
                factory = _create_install_step if name == INSTALL_STEP_NAME else _create_select_step
                desired_steps.append(factory(self.comment_cls))

        if not need_reorder:
            self.debug.setdefault("support_steps", "existing")
            return 0

        removal_indices = sorted({idx for indices in occurrences.values() for idx in indices}, reverse=True)
        new_target_index = target_index
        for idx in removal_indices:
            if idx < target_index:
                new_target_index -= 1
            steps.pop(idx)

        for offset, step_obj in enumerate(desired_steps):
            steps.insert(new_target_index + offset, step_obj)

        self.changed = True
        self.debug["support_steps"] = "inserted" if missing else "reordered"
        new_runner_index = steps.index(runner_step)
        install_new = str(new_runner_index - len(desired_names))
        select_new = str(new_runner_index - 1)
        message = "true نصب:{install_orig}→{install_new} انتخاب:{select_orig}→{select_new}".format(
            install_orig=original_indices[INSTALL_STEP_NAME],
            install_new=install_new,
            select_orig=original_indices[SELECT_STEP_NAME],
            select_new=select_new,
        )
        self.debug["reordered_ruamel"] = message
        return len(desired_steps)

    @staticmethod
    def _normalize_name(value: object) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        if cleaned.startswith(("'", '"')) and len(cleaned) >= 2 and cleaned.endswith(cleaned[0]):
            cleaned = cleaned[1:-1]
        return cleaned

    def _build_job_offset_map(self, source_text: str) -> dict[str, tuple[int, int]]:
        lines = source_text.splitlines()
        newline = "\r\n" if "\r\n" in source_text else "\n"
        newline_len = len(newline)
        offsets = [0]
        running = 0
        for line in lines:
            running += len(line) + newline_len
            offsets.append(running)
        job_map: dict[str, tuple[int, int]] = {}
        jobs_indent: Optional[int] = None
        job_indent: Optional[int] = None
        idx = 0
        while idx < len(lines):
            indent, stripped = _split_indent(lines[idx])
            if stripped.startswith("jobs:"):
                jobs_indent = indent
                job_indent = None
                idx += 1
                continue
            if jobs_indent is None:
                idx += 1
                continue
            if not stripped or stripped.startswith("-") or not stripped.endswith(":"):
                idx += 1
                continue
            if job_indent is None:
                if indent > jobs_indent:
                    job_indent = indent
                else:
                    idx += 1
                    continue
            if indent != job_indent:
                idx += 1
                continue
            name_part = stripped.split(":", 1)[0]
            start_idx = idx
            end_idx = start_idx + 1
            while end_idx < len(lines):
                n_indent, n_stripped = _split_indent(lines[end_idx])
                if n_stripped and n_indent <= job_indent:
                    break
                end_idx += 1
            start_offset = offsets[start_idx]
            end_offset = offsets[end_idx] if end_idx <= len(lines) else offsets[-1]
            job_map[name_part] = (start_offset, end_offset)
            idx = end_idx
        return job_map

    def _rewrite_step(self, job: dict, index: int) -> None:
        steps = job["steps"]
        step = steps[index]
        name = step.get("name")
        if isinstance(name, str):
            if not name.endswith(RUNNER_STEP_SUFFIX):
                step["name"] = f"{name}{RUNNER_STEP_SUFFIX}"
                self.changed = True
        else:
            step["name"] = f"Run pytest suite{RUNNER_STEP_SUFFIX}"
            self.changed = True
        if step.get("run") != RUNNER_COMMAND:
            step["run"] = RUNNER_COMMAND
            self.changed = True
        self.debug["step_after"] = str(index)
        env = step.setdefault("env", self.comment_cls() if self.comment_cls else {})
        if isinstance(env, dict):
            if env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
                env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
                self.changed = True
                self.debug["env_action"] = "augmented"
            else:
                self.debug.setdefault("env_action", "present")
        else:
            step["env"] = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            self.changed = True
            self.debug["env_action"] = "created"


def _apply_ruamel(path: Path) -> tuple[str, str, dict[str, str]]:
    YAML, CommentedMap = _load_ruamel()
    if YAML is None or CommentedMap is None:
        raise ImportError
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    original = path.read_text(encoding="utf-8")
    data = yaml.load(original)
    patcher = RuamelWorkflowPatcher(original, data, CommentedMap)
    changed = patcher.patch()
    if not changed:
        return original, original, patcher.debug
    buffer = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    yaml.dump(data, buffer)
    buffer.seek(0)
    updated = buffer.read().decode("utf-8")
    return original, updated, patcher.debug


def _apply_text(path: Path) -> tuple[str, str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    patcher = TextWorkflowPatcher(text)
    updated = patcher.patch()
    if updated == text:
        return text, text, patcher.debug
    return text, updated, patcher.debug


def _write_atomic(path: Path, content: str) -> None:
    prefix = f".{path.name}.{random.randint(0, 99999)}"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=prefix,
        suffix=".part",
    ) as handle:
        handle.write(content)
        if not content.endswith("\n"):
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp = Path(handle.name)
    temp.replace(path)


def _print_diff(original: str, updated: str, path: Path) -> None:
    diff = difflib.unified_diff(
        original.splitlines(),
        updated.splitlines(),
        fromfile=str(path),
        tofile=str(path),
        lineterm="",
    )
    for line in diff:
        print(line)


def run(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="به‌روزرسانی گردش‌کار pytest")
    parser.add_argument("root", nargs="?", default=".", help="ریشه مخزن")
    parser.add_argument("--workflow", help="نام فایل گردش‌کار")
    parser.add_argument("--dry-run", action="store_true", help="فقط پیش‌نمایش")
    parser.add_argument("--force-text", action="store_true", help="اجبار حالت متنی")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    _ensure_runner_exists(root)

    try:
        selection = _find_workflow(root, args.workflow)
    except PatchError as exc:
        if str(exc).startswith("PATCH_IDEMPOTENT"):
            print(str(exc))
            return 0
        raise
    path = selection.path

    used_text = args.force_text
    original = updated = ""
    debug: dict[str, str] = {"mode_writer": "unknown"}

    if not args.force_text:
        try:
            original, updated, debug = _apply_ruamel(path)
        except ImportError:
            used_text = True
        except PatchError:
            raise
        except Exception as exc:  # pragma: no cover - best effort logging
            print(
                f"RUAMEL_FAILED: ویرایش ساختاری ممکن نشد ({exc}); حالت متنی اعمال می‌شود",
                file=sys.stderr,
            )
            used_text = True

    if used_text:
        original, updated, debug = _apply_text(path)

    if original == updated:
        print("PATCH_IDEMPOTENT: گردش‌کار قبلاً در وضعیت مطلوب بود")
        return 0

    step_before = debug.get("step_start") or debug.get("step_index", "n/a")
    step_after = debug.get("step_after", step_before)
    debug_line = " ".join(
        [
            f"مسیر={path}",
            f"حالت={'متنی' if used_text else 'ruamel'}",
            f"بازه={debug.get('job_range', 'نامشخص')}",
            f"گام={step_before}→{step_after}",
            f"ماتریس={debug.get('matrix_action', 'n/a')}",
            f"env={debug.get('env_action', 'n/a')}",
            f"بازچینش={debug.get('reordered_ruamel', 'false')}",
        ]
    )
    print(f"DEBUG: {debug_line}")

    _print_diff(original, updated, path)

    if args.dry_run:
        print("پیش‌نمایش فقط خواندنی بود؛ تغییری ذخیره نشد")
        return 0

    _write_atomic(path, updated)
    print(f"فایل {path} با موفقیت به‌روزرسانی شد")
    return 0


def main() -> int:  # pragma: no cover
    try:
        return run()
    except PatchError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
