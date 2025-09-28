"""Deterministic pytest JSON report runner with explicit plugin loading.

This module provides a CI-focused wrapper that guarantees the
``pytest-json-report`` plugin is explicitly loaded even when automatic
discovery is disabled through ``PYTEST_DISABLE_PLUGIN_AUTOLOAD``.

Key responsibilities implemented here:

* Validate that the ``pytest-json-report`` plugin is installed and provide a
  deterministic Persian error message if the dependency is missing.
* Ensure the target reports directory exists before invoking ``pytest``.
* Enforce warning-free test execution by forcing ``-W error``.
* Run ``pytest`` via ``subprocess`` with ``-p pytest_jsonreport`` so the
  plugin loads regardless of environment defaults.
* Re-write the generated JSON artifact using an fsynced ``.part`` file and an
  atomic rename, preventing torn reads for downstream consumers.
* Produce structured JSON log lines that include a correlation identifier to
  aid CI observability without leaking any sensitive details.

The runner is intentionally self-contained and relies exclusively on the
Python standard library to simplify usage within constrained CI systems.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import pathlib
import subprocess
import sys
import uuid
from typing import Iterable, List, MutableMapping, Optional, Sequence


DEFAULT_REPORT_PATH = pathlib.Path("reports/strict_score.json")
PERSIAN_PLUGIN_MISSING_MSG = (
    "SEC_PYTEST_JSON_PLUGIN_MISSING: پلاگین 'pytest-json-report' نصب نشده است؛ "
    "آن را به requirements-dev اضافه کنید یا autoload را موقتاً غیرفعال نکنید."
)
LOG_EVENT_NAME = "pytest_json_gate.run"


def _ensure_plugin_available() -> None:
    """Verify that ``pytest-json-report`` can be imported.

    The runner intentionally performs an explicit import so failures are
    reported deterministically with a Persian error message instead of the
    default English traceback produced by ``pytest``.
    """

    try:
        importlib.import_module("pytest_jsonreport")
    except Exception as exc:  # pragma: no cover - broad catch ensures message
        message = PERSIAN_PLUGIN_MISSING_MSG
        sys.stderr.write(f"{message}\n")
        # Emit a structured log envelope for easier correlation inside CI.
        _emit_structured_log(
            correlation_id=_get_correlation_id(),
            payload={
                "event": LOG_EVENT_NAME,
                "phase": "plugin_import_failed",
                "error_type": exc.__class__.__name__,
                "message": message,
            },
        )
        raise SystemExit(2) from exc


def _get_correlation_id() -> str:
    """Return the correlation identifier for all log lines."""

    existing = os.getenv("CI_CORRELATION_ID")
    if existing:
        return existing
    return str(uuid.uuid4())


def _emit_structured_log(*, correlation_id: str, payload: MutableMapping[str, object]) -> None:
    """Emit a JSON log line with the provided payload."""

    payload = dict(payload)
    payload.setdefault("event", LOG_EVENT_NAME)
    payload.setdefault("correlation_id", correlation_id)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _parse_known_args(argv: Sequence[str]) -> tuple[argparse.Namespace, List[str]]:
    """Parse runner-specific options while preserving passthrough args."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--json-report-file",
        dest="json_report_file",
        default=str(DEFAULT_REPORT_PATH),
    )
    parser.add_argument(
        "--reports-dir",
        dest="reports_dir",
        default="reports",
    )
    known, unknown = parser.parse_known_args(argv)
    return known, list(unknown)


def _collect_pytest_args(
    passthrough: Iterable[str],
    *,
    json_path: pathlib.Path,
    enforce_warnings_as_errors: bool,
) -> List[str]:
    """Construct the final pytest invocation list.

    The resulting argument list guarantees ``pytest-json-report`` is loaded,
    that the JSON report is generated, and that warnings are treated as errors.
    """

    args = list(passthrough)
    plugin_explicit = False
    for index, value in enumerate(args):
        if value == "-p" and index + 1 < len(args) and args[index + 1] == "pytest_jsonreport":
            plugin_explicit = True
            break
        if value.startswith("-p") and "pytest_jsonreport" in value:
            plugin_explicit = True
            break

    if not plugin_explicit:
        args = ["-p", "pytest_jsonreport", *args]

    if not any(arg == "--json-report" for arg in args):
        args.append("--json-report")

    # Re-add the ``--json-report-file`` flag if the caller did not provide it
    # explicitly via passthrough arguments.
    if not any(arg.startswith("--json-report-file") for arg in args):
        args.append(f"--json-report-file={json_path}")

    if enforce_warnings_as_errors and not any(arg.startswith("-W") for arg in args):
        args.extend(["-W", "error"])

    return args


def _prepare_environment(env: Optional[MutableMapping[str, str]] = None) -> MutableMapping[str, str]:
    """Return the environment mapping for the pytest subprocess."""

    result = dict(os.environ if env is None else env)
    # Ensure warnings are treated as errors at the interpreter level as a
    # secondary guard in addition to the CLI ``-W error`` argument.
    result["PYTHONWARNINGS"] = "error"
    return result


def _fsync_directory(path: pathlib.Path) -> None:
    """Ensure directory metadata is flushed to disk after rename."""

    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_rewrite_json(report_path: pathlib.Path) -> None:
    """Rewrite ``report_path`` using atomic ``.part`` mechanics."""

    if not report_path.exists():
        return

    data = report_path.read_bytes()
    part_path = report_path.with_suffix(report_path.suffix + ".part")
    with contextlib.suppress(FileNotFoundError):
        part_path.unlink()

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600
    fd = os.open(part_path, flags, mode)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            part_path.unlink()
        raise

    os.replace(part_path, report_path)
    _fsync_directory(report_path.parent)


def _build_summary_footer(exit_code: int, report_path: pathlib.Path) -> str:
    """Return a concise summary footer for CI logs."""

    status = "passed" if exit_code == 0 else "failed"
    return f"pytest-json-gate: status={status} exit_code={exit_code} json={report_path}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for both CLI usage and testability."""

    _ensure_plugin_available()
    correlation_id = _get_correlation_id()

    argv = list(sys.argv[1:] if argv is None else argv)
    known, passthrough = _parse_known_args(argv)
    json_path = pathlib.Path(known.json_report_file).expanduser().resolve()

    reports_dir = pathlib.Path(known.reports_dir).expanduser().resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the resolved JSON path lives under the reports directory to avoid
    # accidental writes outside the expected tree.
    try:
        json_path.relative_to(reports_dir)
    except ValueError:
        json_path = (reports_dir / json_path.name).resolve()

    _emit_structured_log(
        correlation_id=correlation_id,
        payload={
            "event": LOG_EVENT_NAME,
            "phase": "start",
            "reports_dir": str(reports_dir),
            "json_report_file": str(json_path),
        },
    )

    pytest_args = _collect_pytest_args(
        passthrough,
        json_path=json_path,
        enforce_warnings_as_errors=True,
    )

    env = _prepare_environment()

    command = [sys.executable, "-m", "pytest", *pytest_args]

    _emit_structured_log(
        correlation_id=correlation_id,
        payload={
            "event": LOG_EVENT_NAME,
            "phase": "invoke_pytest",
            "command": command,
        },
    )

    completed = subprocess.run(command, env=env, check=False)
    exit_code = int(completed.returncode)

    try:
        _atomic_rewrite_json(json_path)
        _emit_structured_log(
            correlation_id=correlation_id,
            payload={
                "event": LOG_EVENT_NAME,
                "phase": "artifact_finalized",
                "json_report_file": str(json_path),
                "exit_code": exit_code,
            },
        )
    except Exception as error:
        _emit_structured_log(
            correlation_id=correlation_id,
            payload={
                "event": LOG_EVENT_NAME,
                "phase": "artifact_finalize_failed",
                "json_report_file": str(json_path),
                "error_type": error.__class__.__name__,
            },
        )
        raise

    footer = _build_summary_footer(exit_code, json_path)
    sys.stdout.write(footer + "\n")

    return exit_code


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    sys.exit(main())
