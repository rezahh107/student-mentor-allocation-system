from __future__ import annotations

import argparse
import os
import shlex
import orjson
from typing import Iterable

from .orchestrator import Orchestrator, OrchestratorConfig


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CI orchestration entrypoint")
    parser.add_argument("phase", choices=["install", "test", "all"], help="which phase to execute")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, help="arguments to forward to pytest")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    pytest_args = tuple(args.pytest_args or [])
    config = OrchestratorConfig(
        phase=args.phase,
        pytest_args=pytest_args,
        install_cmd=_cmd_from_env("CI_INSTALL_CMD", default=("python", "-m", "pip", "install", "-r", "requirements.txt")),
        test_cmd=_cmd_from_env("CI_TEST_CMD", default=("pytest",)),
        retries=int(os.environ.get("CI_RETRIES", "3") or 3),
        metrics_enabled=os.environ.get("CI_METRICS") == "1",
        metrics_token=os.environ.get("CI_METRICS_TOKEN"),
        metrics_host=os.environ.get("CI_METRICS_HOST", "127.0.0.1"),
        metrics_port=int(os.environ.get("CI_METRICS_PORT", "9801")),
        timezone=os.environ.get("TZ", "Asia/Tehran"),
        gui_in_scope=os.environ.get("CI_GUI_SCOPE") == "1",
        spec_evidence=_decode_mapping(os.environ.get("CI_SPEC_EVIDENCE")),
        integration_quality=_decode_bool_mapping(os.environ.get("CI_INTEGRATION_FLAGS")),
        runtime_expectations=_decode_bool_mapping(os.environ.get("CI_RUNTIME_FLAGS")),
        next_actions=_decode_list(os.environ.get("CI_NEXT_ACTIONS")),
    )
    orchestrator = Orchestrator(config)
    return orchestrator.run()


def _cmd_from_env(var: str, default: tuple[str, ...] | None = None) -> tuple[str, ...]:
    raw = os.environ.get(var)
    if not raw:
        return default or ()
    return tuple(shlex.split(raw))


def _decode_mapping(raw: str | None) -> dict[str, tuple[bool, str | None]] | None:
    if not raw:
        return None
    data = orjson.loads(raw)
    return {k: (bool(v[0]), v[1]) for k, v in data.items()}


def _decode_bool_mapping(raw: str | None) -> dict[str, bool] | None:
    if not raw:
        return None
    data = orjson.loads(raw)
    return {k: bool(v) for k, v in data.items()}


def _decode_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    data = orjson.loads(raw)
    if isinstance(data, list):
        return [str(item) for item in data]
    return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
