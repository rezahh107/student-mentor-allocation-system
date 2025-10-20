"""Command line interface for the Tailored v2.4 runner."""

from __future__ import annotations

import os
from typing import Callable

import click

from . import __version__
from .bootstrap import BootstrapError, bootstrap, verify_agent_file, verify_schema_files
from .exec_pytest import LAYER_CONFIG, load_pytest_result, run_pytest_layer, run_security_checks
from .logging_utils import configure_logging, correlation_id
from .redis_utils import build_namespace, redis_namespace
from .report import generate_report

configure_logging()


def _handle_exceptions(func: Callable[..., None]) -> Callable[..., None]:
    def wrapper(*args, **kwargs) -> None:
        try:
            func(*args, **kwargs)
        except BootstrapError as exc:
            raise click.ClickException(str(exc))
    return wrapper


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Deterministic CI entrypoint."""


def _prepare_environment(layer: str) -> None:
    os.environ.setdefault("TZ", "Asia/Tehran")
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("PYTHONHASHSEED", "0")
    os.environ["CI_TEST_LAYER"] = layer
    os.environ["CI_CORRELATION_ID"] = correlation_id()


def _execute_layer(layer: str) -> None:
    bootstrap()
    verify_schema_files()
    _prepare_environment(layer)
    namespace_seed = os.getenv("CI_TIMESTAMP_SEED")
    namespace = build_namespace(timestamp_seed=namespace_seed)
    with redis_namespace(namespace) as handle:
        os.environ["REDIS_KEY_PREFIX"] = handle.namespace
        os.environ["CI_REDIS_BACKEND"] = "fakeredis" if handle.using_fakeredis else "redis"
        result = run_pytest_layer(layer, handle)
    run_security_checks(result.layout)
    report = generate_report(result)
    click.echo(report)


@main.command(name="pr")
@_handle_exceptions
def pr_command() -> None:
    """Run the pull-request layer."""

    _execute_layer("pr")


@main.command(name="full")
@_handle_exceptions
def full_command() -> None:
    """Run the nightly/full layer."""

    _execute_layer("full")


@main.command(name="smoke")
@_handle_exceptions
def smoke_command() -> None:
    """Run the targeted smoke layer."""

    _execute_layer("smoke")


@main.command(name="report")
@click.option(
    "--layer",
    "layer",
    type=click.Choice(tuple(LAYER_CONFIG.keys())),
    default="pr",
    show_default=True,
)
@_handle_exceptions
def report_command(layer: str) -> None:
    """Render the strict report from existing artifacts without rerunning tests."""

    verify_agent_file()
    verify_schema_files()
    result = load_pytest_result(layer)
    report = generate_report(result)
    click.echo(report)


if __name__ == "__main__":
    main()
