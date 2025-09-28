from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List

from .normalize import normalize_text

CI_PATTERNS = {
    "github": re.compile(r"\.github/workflows/.+\.yml$"),
    "gitlab": re.compile(r"\.gitlab-ci\.yml$"),
    "azure": re.compile(r"azure-pipelines\.yml$"),
    "jenkins": re.compile(r"Jenkinsfile$"),
}

INSTALL_RE = re.compile(r"install|pip|poetry", re.IGNORECASE)
TEST_RE = re.compile(r"test|pytest|unittest", re.IGNORECASE)
ARTIFACT_RE = re.compile(r"artifact|upload", re.IGNORECASE)
ENV_VARS = {"PYTHONWARNINGS", "HEADLESS", "CI"}


def iter_ci_files(root: Path) -> Iterable[Path]:
    root = root or Path.cwd()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        text = str(rel)
        if any(pattern.search(text) for pattern in CI_PATTERNS.values()):
            yield path


def analyze_ci_file(path: Path) -> Dict[str, List[str]]:
    env_found: set[str] = set()
    steps: set[str] = set()
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = normalize_text(raw_line)
            for var in ENV_VARS:
                if var in line:
                    env_found.add(var)
            if INSTALL_RE.search(line):
                steps.add("install")
            if TEST_RE.search(line):
                steps.add("test")
            if ARTIFACT_RE.search(line):
                steps.add("artifact")
    return {"env": sorted(env_found), "steps": sorted(steps)}
