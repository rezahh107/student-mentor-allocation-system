"""Runtime enforcement ensuring imported dependencies match the lockfile."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from importlib import metadata as importlib_metadata

from .lockfiles import LockedRequirement, load_lockfile


class LockedDependencyError(RuntimeError):
    """Raised when the current environment diverges from the lockfile."""


@dataclass(frozen=True)
class DependencyMismatch:
    name: str
    expected: LockedRequirement | None
    actual_version: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "expected": None if self.expected is None else self.expected.version,
            "actual": self.actual_version,
        }


def _normalize_name(name: str) -> str:
    return name.replace("-", "_").lower()


def _snapshot_environment(distributions: Iterable[importlib_metadata.Distribution]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for dist in distributions:
        metadata = dist.metadata or {}
        name = metadata.get("Name", dist.metadata["Name"])  # type: ignore[index]
        snapshot[_normalize_name(name)] = dist.version or "0"
    return snapshot


def enforce_runtime_dependencies(
    *,
    project_root: Path | None = None,
    lockfile_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    distributions: Iterable[importlib_metadata.Distribution] | None = None,
) -> None:
    environ = dict(os.environ)
    if env:
        environ.update(env)
    base = project_root or Path(environ.get("PROJECT_ROOT", Path.cwd()))
    lock_path = lockfile_path or base / "requirements.lock"
    if not lock_path.exists():
        raise LockedDependencyError("فایل قفل وابستگی پیدا نشد")

    locked = load_lockfile(lock_path)
    current = _snapshot_environment(distributions or importlib_metadata.distributions())

    mismatches: list[DependencyMismatch] = []
    for name, requirement in locked.items():
        actual_version = current.get(name)
        if actual_version is None:
            mismatches.append(DependencyMismatch(name=name, expected=requirement, actual_version=None))
            continue
        if actual_version != requirement.version:
            mismatches.append(
                DependencyMismatch(name=name, expected=requirement, actual_version=actual_version)
            )

    for name in sorted(set(current) - set(locked)):
        mismatches.append(DependencyMismatch(name=name, expected=None, actual_version=current[name]))

    if mismatches:
        details = ", ".join(
            f"{item.name}: انتظار {item.expected.version if item.expected else '-'} اما {item.actual_version}"  # type: ignore[union-attr]
            for item in mismatches
        )
        raise LockedDependencyError(
            f"RELEASE_DEP_MISMATCH: وابستگی‌ها با قفل مطابقت ندارند → {details}"
        )


__all__ = ["enforce_runtime_dependencies", "LockedDependencyError", "DependencyMismatch"]
