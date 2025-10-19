from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from .models import PlanAction, PlanResult, RequirementFile, RequirementLine
from .parser import hash_plan_inputs, parse_requirement_line

SECURITY_TOOLS = {
    "pip-audit",
    "cyclonedx-bom",
    "cyclonedx-python-lib",
    "safety",
    "bandit",
}
DEV_TOOLS = {
    "pytest",
    "coverage",
    "pytest-cov",
    "pytest-xdist",
    "tox",
    "black",
    "ruff",
    "mypy",
}

RUNTIME_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements-security.txt",
    "requirements-ml.txt",
    "requirements-advanced.txt",
)


def classify_requirement(line: RequirementLine) -> str:
    if line.normalized_name in SECURITY_TOOLS:
        return "security"
    if line.normalized_name in DEV_TOOLS:
        return "dev"
    return "runtime"


def ensure_files(repo: Path) -> Dict[str, RequirementFile]:
    files: Dict[str, RequirementFile] = {}
    for filename in RUNTIME_FILES:
        path = repo / filename
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = [parse_requirement_line(raw) for raw in text.splitlines()]
        files[filename] = RequirementFile(path=path, lines=lines, original_text=text, newline=newline)
    return files


def plan(repo: Path, *, policy: str = "A") -> PlanResult:
    files = ensure_files(repo)
    desired: Dict[str, List[str]] = {name: [] for name in files}
    reasons: Dict[str, List[str]] = {name: [] for name in files}

    seen: Dict[str, Tuple[str, RequirementLine]] = {}

    for filename, file in files.items():
        for line in file.lines:
            if not line.normalized_name:
                if line.is_include and filename == "requirements-test.txt":
                    continue
                if line.raw.strip().startswith("#"):
                    desired[filename].append(line.raw.strip())
                continue
            key = line.normalized_name
            category = classify_requirement(line)
            target_file = {
                "security": "requirements-security.txt",
                "dev": "requirements-dev.txt",
                "runtime": "requirements.txt",
            }[category]
            if key in seen:
                prev_file, prev_line = seen[key]
                # Keep stricter specifier
                chosen = select_preferred(prev_line, line)
                seen[key] = (target_file, chosen)
            else:
                seen[key] = (target_file, line)

    runtime_lines: Dict[str, RequirementLine] = {}
    for key, (target_file, line) in seen.items():
        runtime_lines.setdefault(target_file, [])

    arranged: Dict[str, List[RequirementLine]] = {
        "requirements.txt": [],
        "requirements-dev.txt": [],
        "requirements-security.txt": [],
    }

    for key, (target_file, line) in seen.items():
        arranged[target_file].append(line)

    for key, lines in arranged.items():
        sorted_lines = sorted(
            lines,
            key=lambda item: (item.normalized_name or "", item.marker, item.spec),
        )
        desired[key].extend(_render_requirement(line) for line in sorted_lines)

    desired["requirements-test.txt"] = ["-r requirements.txt", "-r requirements-dev.txt"]

    moved_names = {
        line.normalized_name
        for line in arranged["requirements.txt"]
        if line.normalized_name
    }

    for filename in ("requirements-ml.txt", "requirements-advanced.txt"):
        desired[filename] = [
            line.raw.strip()
            for line in files[filename].lines
            if line.raw.strip() and line.normalized_name not in moved_names
        ]

    policy_applied = _ensure_policy_requirements(arranged, desired, policy=policy)
    _ensure_python313_markers(desired)

    actions: Dict[Path, PlanAction] = {}
    for filename, file in files.items():
        updated = "\n".join(desired[filename]).strip()
        if updated:
            updated += "\n"
        if updated != file.original_text:
            actions[file.path] = PlanAction(file=file.path, updated_text=updated, reasons=reasons[filename])

    diff = _generate_diff(files, actions)
    plan_id = hash_plan_inputs(files.values())
    messages = []
    if policy.upper() == "A" and policy_applied:
        messages.append("تعارض نسخه بین pip-audit و cyclonedx-bom شناسایی شد؛ سیاست A اعمال شد.")
    return PlanResult(plan_id=plan_id, policy=policy, actions=actions, diff=diff, messages=messages)


def _ensure_policy_requirements(
    arranged: Dict[str, List[RequirementLine]],
    desired: Dict[str, List[str]],
    *,
    policy: str,
) -> bool:
    security_lines = arranged.get("requirements-security.txt", [])
    names = {line.normalized_name: line for line in security_lines}
    pip_audit = names.get("pip-audit")
    cyclonedx = names.get("cyclonedx-bom")
    if not pip_audit or not cyclonedx:
        return False
    if policy.upper() == "A":
        desired_lines = desired["requirements-security.txt"]
        desired_lines = [line for line in desired_lines if not line.lower().startswith("cyclonedx-bom")]
        desired_lines.append("cyclonedx-bom>=7.1,<8")
        desired_lines.sort()
        desired["requirements-security.txt"] = desired_lines
    else:
        desired_lines = desired["requirements-security.txt"]
        desired_lines = [line for line in desired_lines if not line.lower().startswith("pip-audit")]
        desired_lines.append("pip-audit>=3.0.0")
        desired_lines.sort()
        desired["requirements-security.txt"] = desired_lines
    return True


def _ensure_python313_markers(desired: Dict[str, List[str]]) -> None:
    runtime = desired["requirements.txt"]
    packages = {line.split("==")[0].split(">=")[0].strip(): idx for idx, line in enumerate(runtime)}
    for pkg, marker in ("numpy", 'numpy>=2.1 ; python_version >= "3.13"'), (
        "pandas",
        'pandas>=2.2.3 ; python_version >= "3.13"',
    ):
        existing = [line for line in runtime if line.lower().startswith(pkg)]
        if not existing:
            continue
        if marker not in runtime:
            runtime.append(marker)


def select_preferred(first: RequirementLine, second: RequirementLine) -> RequirementLine:
    if first.marker and not second.marker:
        return second
    if second.marker and not first.marker:
        return first
    # Choose the one with stricter specifier (longer spec string) or marker present
    first_weight = (len(first.spec), 1 if first.marker else 0)
    second_weight = (len(second.spec), 1 if second.marker else 0)
    return first if first_weight >= second_weight else second


def _render_requirement(line: RequirementLine) -> str:
    if not line.name:
        return line.raw.strip()
    requirement = line.name
    if line.extras:
        requirement += f"[{line.extras}]"
    if line.spec:
        requirement += line.spec
    if line.marker:
        requirement += f" ; {line.marker}"
    return requirement


def _generate_diff(files: Dict[str, RequirementFile], actions: Dict[Path, PlanAction]) -> str:
    import difflib

    diff_chunks: List[str] = []
    for filename in sorted(files.keys()):
        file = files[filename]
        updated = actions.get(file.path)
        new_text = updated.updated_text if updated else file.original_text
        old_lines = file.original_text.splitlines()
        new_lines = new_text.splitlines()
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=file.path.as_posix(),
            tofile=file.path.as_posix(),
            lineterm="",
        )
        diff_chunks.extend(list(diff))
    return "\n".join(diff_chunks)
