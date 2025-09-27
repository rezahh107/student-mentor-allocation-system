"""Dependency lockfile generation and validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from importlib import metadata as importlib_metadata

from .atomic import atomic_write_lines
from .hashing import sha256_bytes


@dataclass(frozen=True)
class LockedRequirement:
    name: str
    version: str
    hash_value: str

    def render(self) -> str:
        normalized = f"{self.name}=={self.version}"
        return f"{normalized} --hash=sha256:{self.hash_value}"


def _normalize_name(name: str) -> str:
    return name.replace("-", "_").lower()


def _collect_installed(distributions: Iterable[importlib_metadata.Distribution]) -> dict[str, LockedRequirement]:
    requirements: dict[str, LockedRequirement] = {}
    for dist in distributions:
        metadata = dist.metadata or {}
        name = _normalize_name(metadata.get("Name", dist.metadata["Name"]))  # type: ignore[index]
        version = dist.version or "0"
        hash_input = f"{name}=={version}".encode("utf-8")
        requirements[name] = LockedRequirement(name=name, version=version, hash_value=sha256_bytes(hash_input))
    return dict(sorted(requirements.items()))


def generate_lockfile(
    *,
    requirements: Iterable[str],
    output: Path,
) -> list[LockedRequirement]:
    locked: list[LockedRequirement] = []
    for line in sorted(requirements):
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise ValueError(f"ورودی قفل وابستگی نامعتبر است: {line!r}")
        name, version = [part.strip() for part in line.split("==", 1)]
        normalized = _normalize_name(name)
        hash_value = sha256_bytes(f"{normalized}=={version}".encode("utf-8"))
        locked.append(LockedRequirement(name=normalized, version=version, hash_value=hash_value))
    atomic_write_lines(output, [item.render() for item in locked])
    return locked


def snapshot_environment(
    lock_path: Path,
    *,
    constraints_path: Path | None = None,
    distributions: Iterable[importlib_metadata.Distribution] | None = None,
) -> list[LockedRequirement]:
    dists = distributions or importlib_metadata.distributions()
    locked = _collect_installed(dists)
    rendered = [item.render() for item in locked.values()]
    atomic_write_lines(lock_path, rendered)
    if constraints_path is not None:
        atomic_write_lines(constraints_path, [f"{req.name}=={req.version}" for req in locked.values()])
    return list(locked.values())


def load_lockfile(path: Path) -> dict[str, LockedRequirement]:
    requirements: dict[str, LockedRequirement] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 or "--hash=" not in parts[-1]:
            raise ValueError(f"قالب فایل قفل نامعتبر است: {line}")
        req = parts[0]
        if "==" not in req:
            raise ValueError(f"قفل وابستگی بدون نسخه: {line}")
        name, version = req.split("==", 1)
        hash_part = parts[-1].split("--hash=sha256:", 1)[1]
        requirements[_normalize_name(name)] = LockedRequirement(
            name=_normalize_name(name),
            version=version,
            hash_value=hash_part,
        )
    return requirements


__all__ = [
    "LockedRequirement",
    "generate_lockfile",
    "snapshot_environment",
    "load_lockfile",
]
