"""Helpers to maintain release.json with audit artifacts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.phase7_release.atomic import atomic_write


@dataclass(slots=True)
class ManifestEntry:
    name: str
    sha256: str
    size: int
    ts: str
    kind: str


class ReleaseManifest:
    """Mutates a manifest file capturing digests deterministically."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            return json.loads(self._path.read_text("utf-8"))
        return {"audit": {"artifacts": []}}

    def update(self, *, entry: ManifestEntry) -> None:
        manifest = self._load()
        audit_section = manifest.setdefault("audit", {}).setdefault("artifacts", [])
        audit_section = [item for item in audit_section if item.get("name") != entry.name]
        audit_section.append(
            {
                "name": entry.name,
                "sha256": entry.sha256,
                "size": entry.size,
                "ts": entry.ts,
                "kind": entry.kind,
            }
        )
        audit_section.sort(key=lambda item: item["name"])
        manifest["audit"]["artifacts"] = audit_section
        atomic_write(
            self._path,
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )


def make_manifest_entry(path: Path, *, sha256: str, kind: str, ts: datetime) -> ManifestEntry:
    return ManifestEntry(
        name=path.as_posix(),
        sha256=sha256,
        size=path.stat().st_size,
        ts=ts.isoformat(),
        kind=kind,
    )


__all__ = ["ReleaseManifest", "ManifestEntry", "make_manifest_entry"]
