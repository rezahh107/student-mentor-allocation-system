from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from packaging.requirements import Requirement as _RequirementType
    from packaging.specifiers import SpecifierSet as _SpecifierSet
    from packaging.version import InvalidVersion as _InvalidVersionType
    from packaging.version import Version as _VersionType

try:  # pragma: no cover - optional dependency bootstrap
    from prometheus_client import CollectorRegistry, Counter, Gauge, write_to_textfile
except ModuleNotFoundError:  # pragma: no cover - fallback for bare environments
    class _NullMetric:
        def labels(self, *args: object, **kwargs: object) -> "_NullMetric":
            return self

        def inc(self, *args: object, **kwargs: object) -> None:
            return None

        def set(self, *args: object, **kwargs: object) -> None:
            return None

    class CollectorRegistry:  # type: ignore[override]
        def __init__(self) -> None:
            self._metrics: list[str] = []

    def Counter(*args: object, **kwargs: object) -> _NullMetric:  # type: ignore[misc]
        return _NullMetric()

    def Gauge(*args: object, **kwargs: object) -> _NullMetric:  # type: ignore[misc]
        return _NullMetric()

    def write_to_textfile(path: str, registry: CollectorRegistry) -> None:  # type: ignore[override]
        Path(path).write_text("# prometheus-client not installed\n", encoding="utf-8")


def _bootstrap_sys_path() -> None:
    """Ensure the repository src/ directory is importable.

    The dependency manager must work in clean CI environments where the project
    package has not yet been installed. We therefore inject the repository's
    ``src`` directory near the front of ``sys.path`` deterministically so that
    helpers such as ``sma.repo_doctor.clock`` remain available.
    """

    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "src"
    if src_path.exists():
        resolved = str(src_path)
        if resolved not in sys.path:
            sys.path.insert(0, resolved)


_bootstrap_sys_path()

try:
    from sma.repo_doctor.clock import tehran_clock
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    from sma.core.clock import tehran_clock  # type: ignore


AGENTS_SENTINEL = "AGENTS.md"
PERSIAN_LOCK_MISSING = "«قفل وابستگی‌ها منقضی/مفقود است؛ ابتدا دستور make lock را اجرا کنید.»"
PERSIAN_AGENTS_MISSING = "«پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.»"
PERSIAN_EXTRAS_CONFLICT = (
    "«نسخهٔ {package} در extras با پایه ناسازگار است؛ بازهٔ واحد تعیین کنید.» "
    "[requirements.in → {base_spec} از {base_source} | requirements-dev.in → {extras_spec} از {extras_source}] "
    "(Conflict: extras spec for {package} in {extras_source} vs base spec in {base_source})"
)
PERSIAN_GUARD_PACKAGING_MISSING = (
    "«پیش‌نیازهای نگهبان (packaging) نصب نیست؛ ابتدا مرحلهٔ Install (constraints-only) را اجرا کنید.»"
)
PERSIAN_REQUIRE_HASHES_CONFLICT = (
    "«حالت require-hashes با مسیر constraints-only ناسازگار است؛ یا متغیر PIP_REQUIRE_HASHES را خالی کنید، یا از فایل‌های requirements*.txt دارای هش استفاده کنید.»"
)
PERSIAN_GUARD_BOOTSTRAP_FAILED = "«نصب پیش‌نیازهای نگهبان ناموفق بود؛ گزارش CI را بررسی کنید.»"
DEFAULT_RETRIES = 3
MAX_INSTALL_SECONDS = 480


@dataclass(frozen=True)
class _PackagingBundle:
    requirement_cls: type
    canonicalize_name: Callable[[str], str]
    version_cls: type
    invalid_version_cls: type


_PACKAGING_RESOURCES: Optional[_PackagingBundle] = None


@dataclass(frozen=True)
class RequirementRecord:
    name: str
    raw: str
    source: Path
    requirement: Any


def _iter_requirement_lines(path: Path) -> Iterable[str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-"):
            # Support -r includes and pip compile options; treat as metadata.
            continue
        yield stripped
@contextmanager
def _file_lock(lock_path: Path) -> Iterable[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if platform.system() == "Windows":  # pragma: no cover - windows path
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if platform.system() == "Windows":  # pragma: no cover
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_write(path: Path, data: str | bytes, *, encoding: str = "utf-8") -> None:
    target = path
    tmp = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        payload = data.encode(encoding)
    else:
        payload = data
    with open(tmp, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)
    dir_fd = None
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    try:
        if directory_flag:
            dir_fd = os.open(str(target.parent), directory_flag)
            os.fsync(dir_fd)
    finally:
        if dir_fd is not None:
            os.close(dir_fd)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class DependencyManager:
    def __init__(
        self,
        root: Path,
        *,
        correlation_id: str | None = None,
        metrics_path: Path | None = None,
    ) -> None:
        self.root = root
        self.metrics_path = metrics_path or root / "reports" / "deps.prom"
        self.clock = tehran_clock()
        self.correlation_id = correlation_id or self._derive_correlation_id()
        self.registry = CollectorRegistry()
        self._packaging_bundle: Optional[_PackagingBundle] = None
        self.install_attempts = Counter(
            "deps_install_attempts_total",
            "Total install attempts",
            ["status"],
            registry=self.registry,
        )
        self.install_retries = Counter(
            "deps_install_retries_total",
            "Total install retries",
            ["status"],
            registry=self.registry,
        )
        self.install_duration = Gauge(
            "deps_install_runtime_seconds",
            "Duration of dependency installation phases",
            ["phase"],
            registry=self.registry,
        )
        self.packaging_missing = Counter(
            "guard_packaging_missing_total",
            "Total guard packaging bootstrap failures",
            registry=self.registry,
        )
        self.log("init", stage="bootstrap")

    def log(self, event: str, **fields: object) -> None:
        payload = {
            "event": event,
            "correlation_id": self.correlation_id,
            "ts": self.clock.now().isoformat(),
            **fields,
        }
        print(json.dumps(payload, ensure_ascii=False))

    def _get_packaging_bundle(self) -> _PackagingBundle:
        if self._packaging_bundle is not None:
            return self._packaging_bundle
        global _PACKAGING_RESOURCES
        if _PACKAGING_RESOURCES is None:
            try:
                from packaging.requirements import Requirement
                from packaging.utils import canonicalize_name
                from packaging.version import InvalidVersion, Version
            except ModuleNotFoundError:
                self._handle_packaging_missing()
            else:
                _PACKAGING_RESOURCES = _PackagingBundle(
                    requirement_cls=Requirement,
                    canonicalize_name=canonicalize_name,
                    version_cls=Version,
                    invalid_version_cls=InvalidVersion,
                )
        self._packaging_bundle = _PACKAGING_RESOURCES
        return self._packaging_bundle

    def _handle_packaging_missing(self) -> None:
        self.packaging_missing.inc()
        self.log("packaging_missing", outcome="fatal")
        print(PERSIAN_GUARD_PACKAGING_MISSING, file=sys.stderr)
        raise SystemExit(2)

    def normalize_name(self, name: str) -> str:
        bundle = self._get_packaging_bundle()
        return bundle.canonicalize_name(name)

    def _requirement_from_raw(self, raw: str) -> Any:
        bundle = self._get_packaging_bundle()
        return bundle.requirement_cls(raw)

    @staticmethod
    def _env_truthy(value: Optional[str]) -> bool:
        if value is None:
            return False
        normalized = value.strip().lower()
        return normalized not in {"", "0", "false", "no", "off"}

    def _hash_enforced(self) -> bool:
        return self._env_truthy(os.getenv("HASH_ENFORCED"))

    def _assert_require_hashes_mode(self, *, hashed: bool) -> None:
        env_value = os.getenv("PIP_REQUIRE_HASHES")
        if self._env_truthy(env_value) and not hashed:
            self.log("require_hashes_conflict", hashed=hashed, env=env_value)
            print(PERSIAN_REQUIRE_HASHES_CONFLICT, file=sys.stderr)
            raise SystemExit(2)

    def _derive_correlation_id(self) -> str:
        seed = (self.root / "requirements.in").read_bytes() + (
            self.root / "requirements-dev.in"
        ).read_bytes()
        digest = hashlib.blake2b(seed, digest_size=8).hexdigest()
        return f"deps-{digest}"

    # == validation ==
    def assert_agents_present(self) -> None:
        if not (self.root / AGENTS_SENTINEL).exists():
            self.log("agents_missing", result="error")
            raise SystemExit(PERSIAN_AGENTS_MISSING)

    def collect_requirements(self) -> list[RequirementRecord]:
        prod = self._load_requirements(self.root / "requirements.in")
        dev = self._load_requirements(self.root / "requirements-dev.in")
        return prod + dev

    def _load_requirements(self, path: Path) -> list[RequirementRecord]:
        records: list[RequirementRecord] = []
        for raw in _iter_requirement_lines(path):
            requirement = self._requirement_from_raw(raw)
            records.append(
                RequirementRecord(
                    name=self.normalize_name(requirement.name),
                    raw=raw,
                    source=path,
                    requirement=requirement,
                )
            )
        return records

    def validate_duplicates(self, records: Sequence[RequirementRecord]) -> None:
        groups: defaultdict[str, list[RequirementRecord]] = defaultdict(list)
        majors: defaultdict[str, set[int]] = defaultdict(set)
        for record in records:
            groups[record.name].append(record)
            version = self._extract_major(record.requirement)
            if version is not None:
                majors[record.name].add(version)

        for name, major_versions in majors.items():
            if len(major_versions) > 1:
                self.log("multiple_major_versions", package=name, majors=sorted(major_versions))
                raise SystemExit(PERSIAN_LOCK_MISSING)

        for name, package_records in groups.items():
            if len(package_records) == 1:
                continue

            extras_records = [record for record in package_records if record.requirement.extras]
            base_records = [record for record in package_records if not record.requirement.extras]
            if base_records and extras_records:
                base_spec = base_records[0].requirement.specifier
                base_spec_str = str(base_spec)
                for extra_record in extras_records:
                    extras_spec = extra_record.requirement.specifier
                    extras_spec_str = str(extras_spec)
                    if extras_spec and (not base_spec or extras_spec_str != base_spec_str):
                        self.log(
                            "extras_conflict",
                            package=name,
                            base=str(base_records[0].source),
                            extras=str(extra_record.source),
                            base_spec=base_spec_str,
                            extras_spec=extras_spec_str,
                        )
                        raise SystemExit(
                            PERSIAN_EXTRAS_CONFLICT.format(
                                package=base_records[0].requirement.name,
                                base_source=str(base_records[0].source.relative_to(self.root)),
                                extras_source=str(extra_record.source.relative_to(self.root)),
                                base_spec=base_spec_str or "(unspecified)",
                                extras_spec=extras_spec_str or "(unspecified)",
                            )
                        )
                    if extras_spec and extras_spec_str == base_spec_str:
                        self.log(
                            "extras_shadow_version",
                            package=name,
                            base=str(base_records[0].source),
                            extras=str(extra_record.source),
                            base_spec=base_spec_str,
                            extras_spec=extras_spec_str,
                        )
                        raise SystemExit(
                            PERSIAN_EXTRAS_CONFLICT.format(
                                package=base_records[0].requirement.name,
                                base_source=str(base_records[0].source.relative_to(self.root)),
                                extras_source=str(extra_record.source.relative_to(self.root)),
                                base_spec=base_spec_str or "(unspecified)",
                                extras_spec=extras_spec_str or "(unspecified)",
                            )
                        )

            # Detect identical entries or conflicting duplicates without extras context
            fingerprints = {(record.source, record.raw) for record in package_records}
            if len(fingerprints) != len(package_records):
                first, second = package_records[0], package_records[1]
                self.log(
                    "duplicate_requirement",
                    package=name,
                    first=str(first.source),
                    second=str(second.source),
                )
                raise SystemExit(PERSIAN_LOCK_MISSING)

            if not base_records or not extras_records:
                # Allow identical specifications across manifests (e.g., runtime vs dev).
                specs = {str(record.requirement.specifier) for record in package_records}
                if len(specs) == 1:
                    continue
                # Two independent specifications for the same package are not allowed.
                first, second = package_records[0], package_records[1]
                self.log(
                    "conflicting_specification",
                    package=name,
                    first=str(first.source),
                    second=str(second.source),
                    first_spec=str(first.requirement.specifier),
                    second_spec=str(second.requirement.specifier),
                )
                raise SystemExit(PERSIAN_LOCK_MISSING)

    def _extract_major(self, req: Any) -> int | None:
        bundle = self._get_packaging_bundle()
        specifier = getattr(req, "specifier", None)
        if not specifier:
            return None
        for spec in specifier:
            operator = getattr(spec, "operator", None)
            version = getattr(spec, "version", None)
            if operator == "==" and version is not None:
                try:
                    return bundle.version_cls(version).major
                except bundle.invalid_version_cls:
                    return None
        return None

    def ensure_constraints_fresh(self) -> None:
        metadata_dir = self.root / ".ci"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        targets = {
            "constraints.txt": [self.root / "requirements.in"],
            "constraints-dev.txt": [
                self.root / "requirements.in",
                self.root / "requirements-dev.in",
            ],
        }
        for filename, sources in targets.items():
            constraint_path = self.root / filename
            if not constraint_path.exists():
                self.log("constraint_missing", constraint=filename)
                raise SystemExit(PERSIAN_LOCK_MISSING)
            sha_file = metadata_dir / f"{filename}.sha256"
            recorded = None
            if sha_file.exists():
                recorded = json.loads(sha_file.read_text(encoding="utf-8"))
            payload = {
                "constraint": filename,
                "constraint_sha256": _sha256(constraint_path),
                "sources": self._sources_snapshot(sources),
                "pip_tools_version": self._pip_tools_version(),
                "generated_at": self.clock.now().isoformat(),
            }
            if recorded is None or recorded.get("sources") != payload["sources"]:
                self.log("constraint_stale", constraint=filename)
                raise SystemExit(PERSIAN_LOCK_MISSING)
            if recorded.get("constraint_sha256") != payload["constraint_sha256"]:
                self.log("constraint_drift", constraint=filename)
                raise SystemExit(PERSIAN_LOCK_MISSING)
            if recorded.get("pip_tools_version") != payload["pip_tools_version"]:
                self.log("piptools_mismatch", constraint=filename)
                raise SystemExit(PERSIAN_LOCK_MISSING)

    def _pip_tools_version(self) -> str:
        try:
            from importlib import metadata

            return metadata.version("pip-tools")
        except Exception:  # pragma: no cover - piptools unavailable
            return "unknown"

    # == lock ==
    def lock(self) -> None:
        self.assert_agents_present()
        records = self.collect_requirements()
        self.validate_duplicates(records)
        lock_file = self.root / ".cache" / "deps.lock"
        with _file_lock(lock_file):
            self.log("lock_acquired", lock=str(lock_file))
            if not self._needs_recompile():
                self.log("lock_skip", reason="constraints_fresh")
            else:
                self._run_compile(
                    input_path=self.root / "requirements.in",
                    output_path=self.root / "constraints.txt",
                )
                self._run_compile(
                    input_path=self.root / "requirements-dev.in",
                    output_path=self.root / "constraints-dev.txt",
                )
                self._write_metadata()
        self.write_metrics()

    def _run_compile(self, *, input_path: Path, output_path: Path) -> None:
        part_path = output_path.with_suffix(output_path.suffix + ".part")
        cmd = [
            sys.executable,
            "-m",
            "piptools",
            "compile",
            "--generate-hashes",
            "--allow-unsafe",
            "--strip-extras",
            "--quiet",
            "--output-file",
            str(part_path),
            str(input_path),
        ]
        self.log("pip_compile", command=" ".join(cmd))
        completed = subprocess.run(cmd, capture_output=True, text=True)
        if completed.returncode != 0:
            self.log(
                "pip_compile_failed",
                command=" ".join(cmd),
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            raise SystemExit(PERSIAN_LOCK_MISSING)
        _atomic_write(output_path, part_path.read_bytes())
        part_path.unlink(missing_ok=True)

    def _write_metadata(self) -> None:
        meta_dir = self.root / ".ci"
        meta_dir.mkdir(parents=True, exist_ok=True)
        entries = {
            "constraints.txt": [self.root / "requirements.in"],
            "constraints-dev.txt": [
                self.root / "requirements.in",
                self.root / "requirements-dev.in",
            ],
        }
        for filename, sources in entries.items():
            payload = {
                "constraint": filename,
                "constraint_sha256": _sha256(self.root / filename),
                "sources": self._sources_snapshot(sources),
                "pip_tools_version": self._pip_tools_version(),
                "generated_at": self.clock.now().isoformat(),
            }
            _atomic_write(meta_dir / f"{filename}.sha256", json.dumps(payload, ensure_ascii=False))

    def _sources_snapshot(self, sources: Sequence[Path]) -> dict[str, dict[str, int]]:
        snapshot: dict[str, dict[str, int]] = {}
        for src in sources:
            relative = str(src.relative_to(self.root))
            snapshot[relative] = {
                "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                "size": src.stat().st_size,
            }
        return snapshot

    def _needs_recompile(self) -> bool:
        entries = {
            "constraints.txt": [self.root / "requirements.in"],
            "constraints-dev.txt": [
                self.root / "requirements.in",
                self.root / "requirements-dev.in",
            ],
        }
        meta_dir = self.root / ".ci"
        pip_tools_version = self._pip_tools_version()
        for filename, sources in entries.items():
            constraint_path = self.root / filename
            meta_path = meta_dir / f"{filename}.sha256"
            if not constraint_path.exists() or not meta_path.exists():
                return True
            try:
                recorded = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return True
            expected_sources = self._sources_snapshot(sources)
            if recorded.get("sources") != expected_sources:
                return True
            if recorded.get("constraint_sha256") != _sha256(constraint_path):
                return True
            if recorded.get("pip_tools_version") != pip_tools_version:
                return True
        return False

    # == install ==
    def bootstrap_guard_packages(self, *, constraints: Path, packages: Sequence[str]) -> None:
        self.assert_agents_present()
        if not constraints.exists():
            self.log("bootstrap_constraints_missing", constraint=str(constraints))
            raise SystemExit(PERSIAN_LOCK_MISSING)
        self.log(
            "bootstrap_guard_start",
            constraints=str(constraints),
            packages=list(packages),
        )
        self._assert_require_hashes_mode(hashed=False)
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-c",
            str(constraints),
            "--no-deps",
            *packages,
        ]
        try:
            self._run_pip_command(
                cmd,
                event="pip_guard_bootstrap",
                attempt=1,
                wait_seconds=0.0,
            )
        except subprocess.CalledProcessError as error:
            self.log(
                "bootstrap_guard_failed",
                returncode=error.returncode,
                stderr=error.stderr,
            )
            print(PERSIAN_GUARD_BOOTSTRAP_FAILED, file=sys.stderr)
            raise SystemExit(2)
        else:
            self.log("bootstrap_guard_success", packages=list(packages))

    def install(self, *, dev: bool = True, attempts: int = DEFAULT_RETRIES) -> None:
        self.assert_agents_present()
        constraints = self.root / ("constraints-dev.txt" if dev else "constraints.txt")
        hashed_mode = self._hash_enforced()
        manifest_name = "requirements-dev.txt" if dev else "requirements.txt"
        fallback_manifest_name = "requirements-dev.in" if dev else "requirements.in"
        manifest = self.root / (manifest_name if hashed_mode else fallback_manifest_name)
        if not constraints.exists():
            self.log("install_missing_constraints", constraint=str(constraints))
            raise SystemExit(PERSIAN_LOCK_MISSING)
        if not manifest.exists():
            self.log("install_missing_manifest", manifest=str(manifest))
            raise SystemExit(PERSIAN_LOCK_MISSING)
        self.ensure_constraints_fresh()
        self._assert_require_hashes_mode(hashed=hashed_mode)

        upgrade_cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-U",
            "pip",
            "wheel",
        ]
        install_cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-c",
            str(constraints),
        ]
        if hashed_mode:
            install_cmd.extend(["--require-hashes", "-r", str(manifest)])
        else:
            install_cmd.extend(["-r", str(manifest), "-e", ".[dev]" if dev else "."])
        editable_target = ".[dev]" if dev else "."
        editable_cmd: Optional[list[str]] = None
        if hashed_mode:
            editable_cmd = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "-e",
                editable_target,
            ]
        attempts = max(1, attempts)
        success_attempt = None
        for attempt in range(1, attempts + 1):
            phase = f"install-{attempt}"
            planned_wait = self._deterministic_backoff(attempt)
            self.install_duration.labels(phase).set(0)
            start = time.perf_counter()
            status = "failure"
            try:
                self._run_pip_command(
                    upgrade_cmd,
                    event="pip_upgrade",
                    attempt=attempt,
                    wait_seconds=planned_wait,
                )
                self._run_pip_command(
                    install_cmd,
                    event="pip_install",
                    attempt=attempt,
                    wait_seconds=planned_wait,
                )
                if editable_cmd is not None:
                    self._run_pip_command(
                        editable_cmd,
                        event="pip_editable",
                        attempt=attempt,
                        wait_seconds=planned_wait,
                    )
                status = "success"
                if attempt > 1:
                    self.install_retries.labels(status="success").inc()
                success_attempt = attempt
                break
            except subprocess.CalledProcessError as error:
                status = "failure"
                self.log(
                    "pip_install_failed",
                    attempt=attempt,
                    returncode=error.returncode,
                    stderr=error.stderr,
                )
                self.install_retries.labels(status="failure").inc()
                if attempt == attempts:
                    raise SystemExit(PERSIAN_LOCK_MISSING)
            finally:
                elapsed = time.perf_counter() - start
                self.install_duration.labels(phase).set(elapsed)
                self.install_attempts.labels(status=status).inc()
        self._post_install_validation(constraints)
        self._write_install_marker(
            constraints=constraints,
            manifest=manifest,
            attempts=success_attempt or 1,
        )
        self.write_metrics()

    def _write_install_marker(self, *, constraints: Path, manifest: Path, attempts: int) -> None:
        payload = {
            "status": "success",
            "constraints": constraints.name,
            "manifest": manifest.name,
            "attempts": attempts,
            "generated_at": self.clock.now().isoformat(),
            "correlation_id": self.correlation_id,
        }
        marker_path = self.root / "reports" / "ci-install.json"
        _atomic_write(marker_path, json.dumps(payload, ensure_ascii=False))

    def _run_pip_command(
        self,
        cmd: list[str],
        *,
        event: str,
        attempt: int,
        wait_seconds: float,
    ) -> None:
        env = {**os.environ, "PYTHONWARNINGS": "default", "PIP_REQUIRE_HASHES": ""}
        self.log(event, command=" ".join(cmd), attempt=attempt, wait_seconds=wait_seconds)
        result = subprocess.run(cmd, text=True, capture_output=True, env=env)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )

    def _deterministic_backoff(self, attempt: int) -> float:
        seed = f"{self.correlation_id}:{attempt}".encode("utf-8")
        digest = hashlib.blake2b(seed, digest_size=4).digest()
        jitter = int.from_bytes(digest, "big") / 2**32
        base = min(MAX_INSTALL_SECONDS, float(2 ** (attempt - 1)))
        return round(base + jitter, 6)

    def _post_install_validation(self, constraints: Path) -> None:
        check_cmd = [sys.executable, "-m", "pip", "check"]
        self.log("pip_check", command=" ".join(check_cmd))
        check = subprocess.run(check_cmd, text=True, capture_output=True)
        if check.returncode != 0:
            self.log("pip_check_failed", stderr=check.stderr)
            raise SystemExit(PERSIAN_LOCK_MISSING)
        freeze = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            text=True,
            capture_output=True,
            check=True,
        )
        allowed = self._parse_constraints(constraints)
        for line in freeze.stdout.splitlines():
            if not line or line.startswith("#"):
                continue
            name = self.normalize_name(line.split("==", 1)[0])
            if name not in allowed:
                self.log("freeze_drift", package=name)
                raise SystemExit(PERSIAN_LOCK_MISSING)

    def _parse_constraints(self, path: Path) -> set[str]:
        allowed: set[str] = set()
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "==" in stripped and not stripped.startswith("--"):
                name = self.normalize_name(stripped.split("==", 1)[0].strip())
                allowed.add(name)
        return allowed

    def verify(self) -> None:
        self.assert_agents_present()
        records = self.collect_requirements()
        self.validate_duplicates(records)
        self.ensure_constraints_fresh()
        self.write_metrics()
        self.log("verify_ok", status="clean")

    def write_metrics(self) -> None:
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_lock = self.root / ".cache" / "deps.metrics.lock"
        with _file_lock(metrics_lock):
            temp = self.metrics_path.parent / f"{self.metrics_path.name}.part"
            write_to_textfile(str(temp), self.registry)
            _atomic_write(self.metrics_path, temp.read_bytes())
            temp.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic dependency management guardrails",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--metrics", type=Path, help="Metrics output path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify", help="Validate lockfiles without mutating state")
    sub.add_parser("lock", help="Regenerate constraints atomically")
    install = sub.add_parser("install", help="Install dependencies using constraints")
    install.add_argument("--prod", action="store_true", help="Install only production dependencies")
    install.add_argument("--attempts", type=int, default=DEFAULT_RETRIES)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    manager = DependencyManager(
        args.root.resolve(),
        metrics_path=args.metrics,
        correlation_id=os.getenv("CI_CORRELATION_ID"),
    )
    if args.command == "verify":
        manager.verify()
    elif args.command == "lock":
        manager.lock()
    elif args.command == "install":
        manager.install(dev=not args.prod, attempts=args.attempts)
    else:  # pragma: no cover - safeguard
        parser.error("Unknown command")


if __name__ == "__main__":  # pragma: no cover
    main()
