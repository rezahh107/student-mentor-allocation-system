
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import uuid, difflib, re

AGENTS_ERROR = "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."

SECURITY_TOOLS = {"pip-audit", "cyclonedx-bom"}

@dataclass
class Action:
    updated_text: str
    reasons: list[str]

@dataclass
class PlanResult:
    plan_id: str
    actions: dict[Path, Action]
    diff: str
    messages: list[str]

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""

def _normalize_lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)

def _unified_diff(old: str, new: str, path: Path) -> str:
    a = _normalize_lines(old)
    b = _normalize_lines(new)
    return "".join(difflib.unified_diff(a, b, fromfile=str(path), tofile=str(path), lineterm=""))

def _ensure_agents_md(repo: Path) -> None:
    if not (repo / "AGENTS.md").exists():
        raise FileNotFoundError(AGENTS_ERROR)

def _policy_a_line(line: str) -> str:
    # Enforce cyclonedx-bom>=7.1,<8 regardless of current spec
    if line.strip().startswith("cyclonedx-bom"):
        return "cyclonedx-bom>=7.1,<8\n"
    return line

def _clean_runtime(text: str) -> str:
    out = []
    for ln in text.splitlines(True):
        if ln.strip().split("==")[0].strip() in ("pip-audit",):
            continue
        if ln.strip().startswith("cyclonedx-bom"):
            continue
        out.append(ln)
    return "".join(out)

def _ensure_security(text: str) -> str:
    # Ensure pip-audit and cyclonedx-bom with policy A
    lines = []
    have_pa = False
    have_cdx = False
    for ln in text.splitlines(True):
        name = ln.strip().split("==")[0].split(">=")[0].split("<")[0].strip()
        if not name:
            lines.append(ln); continue
        if name == "pip-audit":
            have_pa = True
            lines.append(ln)  # keep existing pin
        elif name == "cyclonedx-bom":
            have_cdx = True
            lines.append("cyclonedx-bom>=7.1,<8\n")
        else:
            lines.append(ln)
    if not have_pa:
        lines.append("pip-audit==2.7.3\n")
    if not have_cdx:
        lines.append("cyclonedx-bom>=7.1,<8\n")
    return "".join(lines)

def _simplify_test(text: str) -> str:
    return "-r requirements.txt\n-r requirements-dev.txt\n"

def plan(repo: Path, policy: str = "A") -> PlanResult:
    _ensure_agents_md(repo)
    actions: dict[Path, Action] = {}
    messages: list[str] = []
    # Paths
    req = repo / "requirements.txt"
    req_dev = repo / "requirements-dev.txt"
    req_test = repo / "requirements-test.txt"
    req_sec = repo / "requirements-security.txt"

    # requirements.txt => remove security tools
    old = _read_text(req)
    if old:
        new = _clean_runtime(old)
        if new != old:
            actions[req] = Action(new, ["removed security tools from runtime"])

    # requirements-security.txt => ensure policy A enforced
    old = _read_text(req_sec)
    if old or (repo / "requirements.txt").exists():
        new = _ensure_security(old)
        if new != old:
            actions[req_sec] = Action(new, ["enforced Policy A for security tools"])

    # requirements-test.txt => simplify includes
    old = _read_text(req_test)
    if old.strip() != "-r requirements.txt\n-r requirements-dev.txt":
        new = _simplify_test(old)
        actions[req_test] = Action(new, ["standardized test includes"])

    # Build diff
    diffs = []
    for path, action in actions.items():
        prev = _read_text(path)
        diffs.append(_unified_diff(prev, action.updated_text, path))
    diff = "".join(diffs)
    plan_id = uuid.uuid4().hex
    return PlanResult(plan_id=plan_id, actions=actions, diff=diff, messages=messages)
