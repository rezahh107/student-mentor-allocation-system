from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List

import pytest
from prometheus_client import CollectorRegistry

from src.phase6_import_to_sabt.job_runner import DeterministicRedis
from src.phase6_import_to_sabt.metrics import reset_registry


def _sorted_relative_files(base_dir: Path) -> List[str]:
    return sorted(
        str(path.relative_to(base_dir))
        for path in base_dir.glob("**/*")
        if path.exists() and path.is_file()
    )


@dataclass(slots=True)
class CleanupFixtures:
    redis: DeterministicRedis
    registry: CollectorRegistry
    base_dir: Path
    namespace: str

    def flush_state(self) -> None:
        self.redis.flushdb()
        reset_registry(self.registry)

    def context(self, **extra: object) -> Dict[str, object]:
        context: Dict[str, object] = {
            "namespace": self.namespace,
            "redis_keys": sorted(self.redis._store.keys()),  # type: ignore[attr-defined]
            "redis_hash": {k: dict(v) for k, v in self.redis._hash.items()},  # type: ignore[attr-defined]
            "tmp_files": _sorted_relative_files(self.base_dir),
            "registry_metrics": [
                sample.name
                for metric in self.registry.collect()
                for sample in metric.samples
            ],
        }
        if extra:
            context.update(extra)
        return context


@pytest.fixture
def cleanup_fixtures(tmp_path_factory: pytest.TempPathFactory) -> Iterator[CleanupFixtures]:
    namespace = f"import-to-sabt-{uuid.uuid4().hex}"
    base_dir = tmp_path_factory.mktemp(namespace)
    fixtures = CleanupFixtures(
        redis=DeterministicRedis(),
        registry=CollectorRegistry(),
        base_dir=base_dir,
        namespace=namespace,
    )
    fixtures.flush_state()
    yield fixtures
    fixtures.flush_state()
    for path in sorted(base_dir.glob("**/*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()
    leftover = list(base_dir.glob("**/*"))
    assert not leftover, fixtures.context(leaked_paths=[str(p) for p in leftover])
    base_dir.rmdir()
