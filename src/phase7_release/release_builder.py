"""Construct deterministic release bundles for ImportToSabt."""
from __future__ import annotations

import io
import json
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from .atomic import atomic_write, atomic_write_lines
from .hashing import sha256_bytes, sha256_file
from .lockfiles import snapshot_environment
from .sbom import generate_sbom
from .versioning import resolve_build_version


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class ReleaseArtifacts:
    wheel_path: Path
    lockfile_path: Path
    constraints_path: Path
    sbom_path: Path
    release_manifest: Path
    container_tar: Path
    systemd_unit: Path
    procfile: Path
    prometheus_rules: Path
    runbook: Path
    vulnerability_report: Path


class ReleaseBuilder:
    """Coordinate release artifact generation."""

    def __init__(
        self,
        *,
        project_root: Path,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._project_root = Path(project_root)
        self._env = dict(env or os.environ)
        self._clock = clock

    def build(self, output_dir: Path) -> ReleaseArtifacts:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        git_sha = self._env.get("GIT_SHA", "unknown")
        build_tag = self._env.get("BUILD_TAG")
        version = resolve_build_version(build_tag, git_sha)
        build_time = _ensure_utc(self._clock())

        wheel_path = output_dir / f"importtosabt-{version}-py3-none-any.whl"
        self._build_wheel(wheel_path=wheel_path, version=version)

        lockfile_path = output_dir / "requirements.lock"
        locked = snapshot_environment(
            lock_path=lockfile_path,
            constraints_path=output_dir / "constraints.txt",
        )

        constraints_path = output_dir / "constraints.txt"
        if not constraints_path.exists():
            atomic_write_lines(constraints_path, [f"{item.name}=={item.version}" for item in locked])

        sbom_path = output_dir / "sbom.json"
        generate_sbom(sbom_path, clock=lambda: build_time)

        reports_dir = output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        vulnerability_report = reports_dir / "deps_audit.json"
        self._generate_pip_audit_stub(
            vulnerability_report,
            locked_names=[item.name for item in locked],
            generated_at=build_time,
        )

        container_tar = output_dir / "container.tar"
        self._build_container_tar(container_tar, wheel_path=wheel_path, version=version)

        systemd_unit = output_dir / "importtosabt.service"
        self._write_systemd_unit(systemd_unit, version=version)

        procfile = output_dir / "Procfile"
        self._write_procfile(procfile, version=version)

        prometheus_rules = output_dir / "prometheus_alerts.yaml"
        self._write_prometheus_rules(prometheus_rules, version=version)

        runbook = output_dir / "runbook.md"
        self._write_runbook(runbook, version=version)

        manifest_path = output_dir / "release.json"
        self._write_manifest(
            manifest_path,
            version=version,
            git_sha=git_sha,
            build_tag=build_tag,
            build_time=build_time,
            artifacts=[
                wheel_path,
                lockfile_path,
                constraints_path,
                sbom_path,
                container_tar,
                systemd_unit,
                procfile,
                prometheus_rules,
                runbook,
                vulnerability_report,
            ],
        )

        return ReleaseArtifacts(
            wheel_path=wheel_path,
            lockfile_path=lockfile_path,
            constraints_path=constraints_path,
            sbom_path=sbom_path,
            release_manifest=manifest_path,
            container_tar=container_tar,
            systemd_unit=systemd_unit,
            procfile=procfile,
            prometheus_rules=prometheus_rules,
            runbook=runbook,
            vulnerability_report=vulnerability_report,
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
            data = f"#!/bin/sh\nset -euo pipefail\nexec python -m importtosabt.api --version {version}\n".encode("utf-8")
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

    def _write_systemd_unit(self, path: Path, *, version: str) -> None:
        unit = [
            "[Unit]",
            "Description=ImportToSabt API",
            "After=network.target",
            "[Service]",
            "Type=notify",
            "Environment=PYTHONUNBUFFERED=1",
            f"ExecStart=/usr/bin/python -m importtosabt.api --version {version}",
            "Restart=on-failure",
            "TimeoutStopSec=45",
            "[Install]",
            "WantedBy=multi-user.target",
        ]
        atomic_write_lines(path, unit)

    def _write_procfile(self, path: Path, *, version: str) -> None:
        atomic_write_lines(path, [f"web: python -m importtosabt.api --version {version}"])

    def _write_prometheus_rules(self, path: Path, *, version: str) -> None:
        rules = "\n".join(
            [
                "groups:",
                "  - name: importtosabt-exporter",
                "    interval: 30s",
                "    rules:",
                "      - alert: SabtExporterLatencyHigh",
                "        expr: histogram_quantile(0.95, sum(rate(export_job_latency_seconds_bucket[5m])) by (le)) > 15",
                "        for: 5m",
                "        labels:",
                "          severity: critical",
                "        annotations:",
                "          summary: 'تاخیر زیاد در خروجی سامانه'",
                "          description: 'زمان تکمیل صادرات از آستانه عبور کرده است'",
                "      - alert: SabtExporterRetriesExhausted",
                "        expr: increase(export_job_retry_exhausted_total[10m]) > 0",
                "        for: 1m",
                "        labels:",
                "          severity: warning",
                "        annotations:",
                "          summary: 'تعداد تلاش مجدد زیاد'",
                "          description: 'تعداد تلاش مجدد فراتر از انتظار است'",
                "      - alert: ImportToSabtHealthLatency",
                "        expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{path='/healthz'}[5m])) by (le)) > 0.2",
                "        for: 2m",
                "        labels:",
                "          severity: warning",
                "        annotations:",
                "          summary: 'پاسخ سلامت کند است'",
                "          description: 'نسخه='" + version + "'",
            ]
        )
        atomic_write(path, rules.encode("utf-8"))

    def _write_runbook(self, path: Path, *, version: str) -> None:
        content = "\n".join(
            [
                f"# ImportToSabt Release {version}",
                "## سناریوهای رایج",
                "- برای قطعیت انتشار، از script `deploy_zero_downtime.py` استفاده کنید.",
                "- در صورت نیاز به بازگردانی، از دستور `python -m phase7_release.rollback` بهره ببرید.",
                "## حالت‌های بحرانی",
                "- HEALTH_FAIL: بررسی اتصال پایگاه داده و Redis",
                "- RELEASE_DEP_MISMATCH: اجرای مجدد build با محیط پاک",
            ]
        )
        atomic_write(path, content.encode("utf-8"))

    def _write_manifest(
        self,
        path: Path,
        *,
        version: str,
        git_sha: str,
        build_tag: str | None,
        build_time: datetime,
        artifacts: Iterable[Path],
    ) -> None:
        base_dir = path.parent
        entries = []
        for artifact in sorted(artifacts, key=lambda p: str(p.relative_to(base_dir))):
            relative = artifact.relative_to(base_dir)
            entries.append(
                {
                    "name": relative.as_posix(),
                    "sha256": sha256_file(artifact),
                    "size": artifact.stat().st_size,
                }
            )
        manifest = {
            "version": version,
            "git_sha": git_sha,
            "build_tag": build_tag,
            "built_at": build_time.isoformat(),
            "artifacts": entries,
            "artifact_ids": [entry["sha256"] for entry in entries],
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


def _zip_info(name: str, date_time: tuple[int, int, int, int, int, int]) -> ZipInfo:
    info = ZipInfo(name)
    info.date_time = date_time
    info.compress_type = ZIP_DEFLATED
    return info


__all__ = ["ReleaseBuilder", "ReleaseArtifacts"]
