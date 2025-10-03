"""Construct deterministic release bundles for ImportToSabt."""
from __future__ import annotations

import io
import json
import os
import platform
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from .alerts import AlertCatalog
from .atomic import atomic_write
from .hashing import sha256_bytes, sha256_file
from .lockfiles import snapshot_environment
from .perf_harness import PerfBaseline, PerfHarness
from .sbom import generate_sbom
from .versioning import resolve_build_version

_TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _ensure_tehran(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_TEHRAN_TZ)
    return dt.astimezone(_TEHRAN_TZ)


@dataclass(frozen=True)
class ReleaseBundle:
    """Container for generated release artifacts."""

    root: Path
    wheel: Path
    lockfile: Path
    constraints: Path
    sbom: Path
    deps_audit: Path
    manifest: Path
    perf_report: Path
    container: Path | None
    slo_rules: Path
    error_rules: Path
    alertmanager: Path

    @property
    def wheel_path(self) -> Path:
        return self.wheel

    @property
    def lockfile_path(self) -> Path:
        return self.lockfile

    @property
    def constraints_path(self) -> Path:
        return self.constraints

    @property
    def sbom_path(self) -> Path:
        return self.sbom

    @property
    def release_manifest(self) -> Path:
        return self.manifest

    @property
    def vulnerability_report(self) -> Path:
        return self.deps_audit

    @property
    def container_tar(self) -> Path | None:
        return self.container

    @property
    def prometheus_rules(self) -> Path:
        return self.slo_rules


class ReleaseBuilder:
    """Coordinate reproducible release artifact generation."""

    def __init__(
        self,
        *,
        project_root: Path,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None] | None = None,
        perf_harness: PerfHarness | None = None,
    ) -> None:
        self._project_root = Path(project_root)
        self._env = dict(env or os.environ)
        self._clock = clock
        self._sleep = sleep or time.sleep
        self._perf_harness = perf_harness

    def build(self, output_dir: Path) -> ReleaseBundle:
        release_dir = Path(output_dir)
        release_dir.mkdir(parents=True, exist_ok=True)

        git_sha = self._env.get("GIT_SHA", "unknown")
        build_tag = self._env.get("BUILD_TAG")
        version = resolve_build_version(build_tag, git_sha)
        build_time = _ensure_tehran(self._clock())

        wheel_path = release_dir / f"importtosabt-{version}-py3-none-any.whl"
        self._build_wheel(wheel_path=wheel_path, version=version)

        lockfile_path = release_dir / "requirements.lock"
        constraints_path = release_dir / "constraints.txt"
        locked = snapshot_environment(lock_path=lockfile_path, constraints_path=constraints_path)

        sbom_path = release_dir / "sbom.json"
        generate_sbom(sbom_path, clock=lambda: build_time)

        deps_audit_path = release_dir / "deps_audit.json"
        self._generate_pip_audit_stub(
            deps_audit_path,
            locked_names=[item.name for item in locked],
            generated_at=build_time,
        )

        prom_dir = release_dir / "prom"
        prom_dir.mkdir(parents=True, exist_ok=True)
        alerts = AlertCatalog(clock=lambda: build_time)
        slo_rules = prom_dir / "rules_slo.yml"
        error_rules = prom_dir / "rules_errors.yml"
        alertmanager = prom_dir / "alertmanager.yml"
        alerts.write_slo_rules(slo_rules)
        alerts.write_error_rules(error_rules)
        alerts.write_alertmanager_config(alertmanager)

        reports_dir = release_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        perf_harness = self._perf_harness or PerfHarness()
        perf_report_path = reports_dir / "perf_baseline.json"
        baseline = perf_harness.run(report_path=perf_report_path)

        container_tar = release_dir / "container.tar"
        self._build_container_tar(container_tar, wheel_path=wheel_path, version=version)
        if container_tar.stat().st_size == 0:
            container_tar.unlink(missing_ok=True)
            container_reference: Path | None = None
        else:
            container_reference = container_tar

        manifest_path = release_dir / "release.json"
        self._write_manifest(
            manifest_path,
            version=version,
            git_sha=git_sha,
            build_tag=build_tag,
            build_time=build_time,
            baseline=baseline,
            artifacts=[
                wheel_path,
                lockfile_path,
                constraints_path,
                sbom_path,
                deps_audit_path,
                slo_rules,
                error_rules,
                alertmanager,
                perf_report_path,
            ]
            + ([container_reference] if container_reference else []),
        )

        return ReleaseBundle(
            root=release_dir,
            wheel=wheel_path,
            lockfile=lockfile_path,
            constraints=constraints_path,
            sbom=sbom_path,
            deps_audit=deps_audit_path,
            manifest=manifest_path,
            perf_report=perf_report_path,
            container=container_reference,
            slo_rules=slo_rules,
            error_rules=error_rules,
            alertmanager=alertmanager,
        )

    # ------------------------------- helpers ---------------------------------

    def _build_wheel(self, *, wheel_path: Path, version: str) -> None:
        package_root = self._project_root / "src"
        files: list[tuple[Path, str]] = []
        for path in sorted(package_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(package_root)
            files.append((path, str(relative)))

        dist_info_dir = f"importtosabt-{version}.dist-info"
        metadata = "\n".join(
            [
                "Metadata-Version: 2.1",
                "Name: importtosabt",
                f"Version: {version}",
                "Summary: ImportToSabt production bundle",
                "Requires-Python: >=3.11",
            ]
        ).encode("utf-8")
        wheel_metadata = "\n".join(
            [
                "Wheel-Version: 1.0",
                "Generator: phase7-release",
                "Root-Is-Purelib: true",
                "Tag: py3-none-any",
            ]
        ).encode("utf-8")

        record_entries: list[str] = []
        date_time = (1980, 1, 1, 0, 0, 0)
        with ZipFile(wheel_path, "w", compression=ZIP_DEFLATED) as zf:
            for source, arcname in files:
                info = ZipInfo(arcname)
                info.date_time = date_time
                info.compress_type = ZIP_DEFLATED
                with source.open("rb") as fh:
                    data = fh.read()
                zf.writestr(info, data)
                record_entries.append(
                    f"{arcname},sha256={sha256_bytes(data)}, {len(data)}"
                )

            metadata_name = f"{dist_info_dir}/METADATA"
            zf.writestr(_zip_info(metadata_name, date_time), metadata)
            record_entries.append(
                f"{metadata_name},sha256={sha256_bytes(metadata)}, {len(metadata)}"
            )

            wheel_name = f"{dist_info_dir}/WHEEL"
            zf.writestr(_zip_info(wheel_name, date_time), wheel_metadata)
            record_entries.append(
                f"{wheel_name},sha256={sha256_bytes(wheel_metadata)}, {len(wheel_metadata)}"
            )

            record_name = f"{dist_info_dir}/RECORD"
            record_body = "\n".join(record_entries) + "\n"
            zf.writestr(_zip_info(record_name, date_time), record_body.encode("utf-8"))

    def _generate_pip_audit_stub(
        self,
        target: Path,
        *,
        locked_names: Sequence[str],
        generated_at: datetime,
    ) -> None:
        payload = {
            "generated_at": generated_at.isoformat(),
            "tool": "pip-audit-stub",
            "vulnerabilities": [],
            "packages": sorted(locked_names),
        }
        atomic_write(target, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _build_container_tar(self, target: Path, *, wheel_path: Path, version: str) -> None:
        with tarfile.open(target, "w") as tar:
            data = (
                "#!/bin/sh\n"
                "set -euo pipefail\n"
                "exec python -m importtosabt.api --version "
                + version
                + "\n"
            ).encode("utf-8")
            script_info = tarfile.TarInfo(name="app/entrypoint.sh")
            script_info.mode = 0o755
            script_info.size = len(data)
            script_info.mtime = 0
            tar.addfile(script_info, io.BytesIO(data))
            wheel_stat = wheel_path.stat()
            wheel_info = tarfile.TarInfo(name=f"app/{wheel_path.name}")
            wheel_info.size = wheel_stat.st_size
            wheel_info.mtime = 0
            with wheel_path.open("rb") as fh:
                tar.addfile(wheel_info, fh)

    def _write_manifest(
        self,
        path: Path,
        *,
        version: str,
        git_sha: str,
        build_tag: str | None,
        build_time: datetime,
        baseline: PerfBaseline,
        artifacts: Iterable[Path],
    ) -> None:
        base_dir = path.parent
        entries = []
        for artifact in sorted(artifacts, key=lambda p: p.relative_to(base_dir).as_posix()):
            if artifact is None:
                continue
            relative = artifact.relative_to(base_dir)
            digest = _digest_with_retry(artifact, sleep=self._sleep)
            entries.append(
                {
                    "name": relative.as_posix(),
                    "sha256": digest,
                    "size": artifact.stat().st_size,
                }
            )
        manifest = {
            "version": version,
            "git_sha": git_sha,
            "build_tag": build_tag,
            "build_ts": build_time.isoformat(),
            "build_inputs": {
                "python": platform.python_version(),
                "lock": "requirements.lock",
                "constraints": "constraints.txt",
            },
            "artifacts": entries,
            "artifact_ids": [entry["sha256"] for entry in entries],
            "perf_baseline": baseline.to_dict(),
        }
        atomic_write(
            path,
            json.dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
        )


def _digest_with_retry(path: Path, *, attempts: int = 4, sleep: Callable[[float], None]) -> str:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return sha256_file(path)
        except OSError as exc:  # pragma: no cover - rare FS flake
            last_error = exc
            delay = 0.05 * attempt + _deterministic_jitter(path.name, attempt)
            sleep(delay)
    raise RuntimeError(f"DIGEST_FAILED: path={path}; last_error={last_error}")


def _deterministic_jitter(key: str, attempt: int) -> float:
    seed = sha256_bytes(f"{key}:{attempt}".encode("utf-8"))
    fraction = int(seed[:12], 16) / float(0xFFFFFFFFFFFF)
    return fraction * 0.02


def _zip_info(name: str, date_time: tuple[int, int, int, int, int, int]) -> ZipInfo:
    info = ZipInfo(name)
    info.date_time = date_time
    info.compress_type = ZIP_DEFLATED
    return info


ReleaseArtifacts = ReleaseBundle


__all__ = ["ReleaseBuilder", "ReleaseBundle", "ReleaseArtifacts"]
