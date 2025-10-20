"""Semantic version helpers for deterministic release builds."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@dataclass(frozen=True)
class BuildMetadata:
    """Lightweight container describing build identification data."""

    tag: str | None
    git_sha: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BuildMetadata":
        environ = os.environ if env is None else env
        return cls(tag=environ.get("BUILD_TAG"), git_sha=environ.get("GIT_SHA", "unknown"))


def _normalize_sha(git_sha: str) -> str:
    sha = (git_sha or "unknown").strip()
    if not sha:
        return "unknown"
    return sha.lower()[:40]


def resolve_build_version(tag: str | None, git_sha: str | None) -> str:
    """Return a normalized semantic version string."""

    sha = _normalize_sha(git_sha or "unknown")
    if tag:
        match = _SEMVER_RE.match(tag.strip())
        if not match:
            raise ValueError(f"برچسب نگارش نامعتبر است: {tag!r}")
        major = int(match.group("major"))
        minor = int(match.group("minor"))
        patch = int(match.group("patch"))
        prerelease = match.group("prerelease")
        build = match.group("build")
        version = f"{major}.{minor}.{patch}"
        if prerelease:
            version += f"-{prerelease}"
        normalized_build = []
        if build:
            normalized_build.append(build)
        normalized_build.append(sha[:12])
        version += "+" + ".".join(normalized_build)
        return version
    return f"0.0.0+{sha[:12]}"


__all__ = ["BuildMetadata", "resolve_build_version"]
