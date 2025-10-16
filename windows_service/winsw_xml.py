"""WinSW XML generator with atomic writes and observability."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile
from typing import Mapping
from uuid import uuid4
from xml.etree import ElementTree as ET

from prometheus_client import CollectorRegistry, Counter, REGISTRY

from src.infrastructure.monitoring.logging_adapter import correlation_id_var
from src.phase6_import_to_sabt.sanitization import sanitize_text, secure_digest
from windows_service.errors import ServiceError
from windows_service.normalization import sanitize_env_text

LOGGER = logging.getLogger(__name__)

REQUIRED_KEYS = ("DATABASE_URL", "REDIS_URL", "METRICS_TOKEN")

_XML_DECLARATION = b"<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
_DEFAULT_ENV_MESSAGE = "پیکربندی ناقص است؛ متغیر {variable} خالی است."
_COUNTER_CACHE: dict[int, Counter] = {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _windows_path(path: Path | str) -> str:
    return str(PureWindowsPath(path))


def _strip_quotes(value: str | None) -> str:
    if value is None:
        return ""
    text = value.strip()
    if len(text) >= 2 and (
        (text.startswith('"') and text.endswith('"'))
        or (text.startswith("'") and text.endswith("'"))
    ):
        return text[1:-1]
    return text


def _normalise_env_value(name: str, raw: str | None) -> str:
    sanitised = sanitize_env_text(_strip_quotes(raw))
    if not sanitised or sanitised.lower() in {"null", "none", "undefined"}:
        raise ServiceError(
            "CONFIG_MISSING",
            _DEFAULT_ENV_MESSAGE.format(variable=name),
            context={"variable": name},
        )
    return sanitised


def _read_env_file(path: Path) -> Mapping[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = sanitize_text(key)
        if not key:
            continue
        values[key] = _strip_quotes(value.strip())
    return values


def load_env_values(*, env_path: Path | None = None) -> dict[str, str]:
    repo_root = _repo_root()
    env_file = env_path or (repo_root / ".env.dev")
    file_values = _read_env_file(env_file)
    resolved: dict[str, str] = {}
    for key in REQUIRED_KEYS:
        candidate = os.getenv(key)
        if candidate is None:
            candidate = file_values.get(key)
        resolved[key] = _normalise_env_value(key, candidate)
    return resolved


def _indent(element: ET.Element, level: int = 0) -> None:
    indent = "\n" + level * "  "
    children = list(element)
    if children:
        if not element.text or not element.text.strip():
            element.text = indent + "  "
        for child in children:
            _indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent + "  "
        last = children[-1]
        if not last.tail or not last.tail.strip():
            last.tail = indent
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indent


def _resolve_pwsh_path(explicit: str | None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env_override = os.getenv("SMASM_PWSH")
    if env_override:
        candidates.append(env_override)
    for candidate in candidates:
        text = sanitize_env_text(candidate)
        if text:
            return _windows_path(Path(text))
    for binary in ("pwsh", "pwsh.exe"):
        located = shutil.which(binary)
        if located:
            return _windows_path(Path(located))
    raise ServiceError(
        "POWERSHELL_MISSING",
        "پروندهٔ اجرای PowerShell 7 یافت نشد.",
        context={},
    )


def render_winsw_xml(
    env_values: Mapping[str, str],
    *,
    repo_root: Path | None = None,
    pwsh_path: str | None = None,
    pretty: bool = False,
) -> bytes:
    repo = (repo_root or _repo_root()).resolve()
    executable = _resolve_pwsh_path(pwsh_path)

    root = ET.Element("service")
    ET.SubElement(root, "id").text = "StudentMentorService"
    ET.SubElement(root, "name").text = "Student Mentor Service"
    ET.SubElement(root, "description").text = (
        "FastAPI backend for ImportToSabt (managed by WinSW)."
    )

    ET.SubElement(root, "executable").text = executable
    start_script = _windows_path(repo / "Start-App.ps1")
    ET.SubElement(root, "arguments").text = (
        f"-NoLogo -NoProfile -ExecutionPolicy Bypass -File {start_script}"
    )
    ET.SubElement(root, "workingdirectory").text = _windows_path(repo)

    log = ET.SubElement(root, "log", mode="roll-by-size")
    ET.SubElement(log, "sizeThreshold").text = "10485760"
    ET.SubElement(log, "keepFiles").text = "8"

    base_env = {
        "PYTHONUTF8": "1",
        "PYTHONPATH": _windows_path(repo / "src"),
    }
    merged = {**base_env, **env_values}
    for key, value in merged.items():
        ET.SubElement(root, "env", name=key, value=value)

    if pretty:
        _indent(root)
    xml_payload = ET.tostring(root, encoding="utf-8")
    return _XML_DECLARATION + xml_payload


def _write_bytes_atomic(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"{destination.name}."
    with NamedTemporaryFile(
        "wb",
        delete=False,
        dir=str(destination.parent),
        prefix=prefix,
        suffix=".part",
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, destination)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()
        raise


def _counter_for(registry: CollectorRegistry) -> Counter:
    cache_key = id(registry)
    existing = _COUNTER_CACHE.get(cache_key)
    if existing is not None:
        return existing
    try:
        counter = Counter(
            "winsw_xml_write_total",
            "Total number of WinSW XML write attempts.",
            labelnames=("outcome",),
            registry=registry,
        )
    except ValueError:
        registry_collector = registry._names_to_collectors.get(  # type: ignore[attr-defined]
            "winsw_xml_write_total"
        )
        if isinstance(registry_collector, Counter):
            counter = registry_collector
        else:  # pragma: no cover - defensive
            raise
    _COUNTER_CACHE[cache_key] = counter
    return counter


def write_winsw_xml(
    *,
    env_path: Path | None = None,
    output_path: Path | None = None,
    repo_root: Path | None = None,
    pwsh_path: str | None = None,
    pretty: bool = False,
    registry: CollectorRegistry | None = None,
) -> Path:
    repo = repo_root or _repo_root()
    repo = repo.resolve()
    env_values = load_env_values(env_path=env_path)
    xml_payload = render_winsw_xml(
        env_values,
        repo_root=repo,
        pwsh_path=pwsh_path,
        pretty=pretty,
    )
    target = output_path or Path(__file__).with_name("StudentMentorService.xml")

    registry = registry or REGISTRY
    counter = _counter_for(registry)
    correlation = correlation_id_var.get()
    if not correlation:
        correlation = secure_digest(f"winsw:{uuid4()}")
        token = correlation_id_var.set(correlation)
    else:
        token = None

    try:
        _write_bytes_atomic(target, xml_payload)
    except Exception as exc:
        counter.labels(outcome="failure").inc()
        LOGGER.error(
            "winsw_xml_write_failed",
            extra={
                "correlation_id": correlation,
                "path": str(target),
                "detail": f"{type(exc).__name__}",
            },
        )
        raise
    else:
        counter.labels(outcome="success").inc()
        LOGGER.info(
            "winsw_xml_write_succeeded",
            extra={
                "correlation_id": correlation,
                "path": str(target),
                "env_keys": json.dumps(sorted(env_values.keys()), ensure_ascii=False),
            },
        )
        return target
    finally:
        if token is not None:
            correlation_id_var.reset(token)


__all__ = [
    "REQUIRED_KEYS",
    "load_env_values",
    "render_winsw_xml",
    "write_winsw_xml",
]
