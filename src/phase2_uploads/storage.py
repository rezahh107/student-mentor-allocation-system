from __future__ import annotations

import os
from dataclasses import dataclass, field
from uuid import uuid4
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class AtomicWriter:
    directory: Path
    suffix: str = ".csv"
    _temp_path: Path | None = field(init=False, default=None)
    _fh: "io.BufferedWriter" | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temp_name = f"{uuid4().hex}{self.suffix}.part"
        self._temp_path = self.directory / temp_name
        self._fh = open(self._temp_path, "wb")

    def write(self, chunk: bytes) -> None:
        assert self._fh is not None
        self._fh.write(chunk)

    def commit(self, final_path: Path) -> Path:
        assert self._fh is not None and self._temp_path is not None
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self._temp_path, final_path)
        dir_fd = os.open(str(final_path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return final_path

    def abort(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:  # pragma: no cover - defensive
                pass
        if self._temp_path and self._temp_path.exists():
            self._temp_path.unlink()


@dataclass(slots=True)
class AtomicStorage:
    base_dir: Path

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def path_for_digest(self, digest: str) -> Path:
        return self.base_dir / "sha256" / f"{digest}.csv"

    def writer(self) -> AtomicWriter:
        return AtomicWriter(directory=self.base_dir / "tmp")

    def finalize(self, digest: str, writer: AtomicWriter) -> Path:
        target = self.path_for_digest(digest)
        if target.exists():
            writer.abort()
            return target
        return writer.commit(target)
