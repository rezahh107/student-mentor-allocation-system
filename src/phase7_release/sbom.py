"""CycloneDX SBOM generation utilities."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from importlib import metadata as importlib_metadata

from .atomic import atomic_write
from .hashing import sha256_bytes


@dataclass(frozen=True)
class SbomComponent:
    name: str
    version: str
    purl: str
    hash_value: str

    def to_dict(self) -> dict[str, object]:
        return {
            "type": "library",
            "name": self.name,
            "version": self.version,
            "purl": self.purl,
            "hashes": [
                {
                    "alg": "SHA-256",
                    "content": self.hash_value,
                }
            ],
        }


def _to_component(dist: importlib_metadata.Distribution) -> SbomComponent:
    metadata = dist.metadata or {}
    name = metadata.get("Name", dist.metadata["Name"])  # type: ignore[index]
    version = dist.version or "0"
    normalized = name.replace(" ", "-")
    purl = f"pkg:pypi/{normalized}@{version}"
    hash_value = sha256_bytes(f"{normalized}@{version}".encode("utf-8"))
    return SbomComponent(name=normalized, version=version, purl=purl, hash_value=hash_value)


def generate_sbom(
    path: Path,
    *,
    distributions: Iterable[importlib_metadata.Distribution] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> list[SbomComponent]:
    dists = list(distributions or importlib_metadata.distributions())
    components = sorted((_to_component(dist) for dist in dists), key=lambda item: item.name.lower())
    now = clock() if clock is not None else datetime.now(tz=timezone.utc)
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "serialNumber": f"urn:uuid:{sha256_bytes(b''.join(item.hash_value.encode('utf-8') for item in components))[:32]}",
        "version": 1,
        "metadata": {
            "timestamp": now.isoformat(),
        },
        "components": [component.to_dict() for component in components],
    }
    atomic_write(path, json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return components


__all__ = ["SbomComponent", "generate_sbom"]
