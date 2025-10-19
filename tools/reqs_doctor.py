from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import click
from tools.reqs_doctor.clock import DeterministicClock
from tools.reqs_doctor.io_utils import atomic_write
from tools.reqs_doctor.obs import DoctorMetrics, JsonLogger
from tools.reqs_doctor.planner import plan as build_plan


@click.group(help="Automatic requirements doctor")
def app() -> None:
    """CLI entrypoint."""
    return None

AGENTS_ERROR = "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."


def ensure_agents_md(repo: Path) -> Path:
    agents_path = repo / "AGENTS.md"
    if not agents_path.exists():
        raise click.BadParameter(AGENTS_ERROR)
    return agents_path


def _correlation_id(plan_id: str) -> str:
    return os.environ.get("X_REQUEST_ID") or plan_id or uuid.uuid4().hex


def _plan(repo: Path, policy: str) -> dict:
    plan_result = build_plan(repo, policy=policy)
    metrics = DoctorMetrics.fresh()
    metrics.observe_plan()
    ndjson_entry = {
        "correlation_id": _correlation_id(plan_result.plan_id),
        "plan_id": plan_result.plan_id,
        "policy": policy,
        "actions": [str(path) for path in sorted(plan_result.actions.keys())],
        "messages": plan_result.messages,
    }
    _append_ndjson(repo / "reports" / "reqs_doctor.ndjson", ndjson_entry)
    return {
        "plan_id": plan_result.plan_id,
        "policy": policy,
        "messages": plan_result.messages,
        "actions": [
            {
                "file": str(path),
                "updated_text": action.updated_text,
                "reasons": action.reasons,
            }
            for path, action in sorted(plan_result.actions.items(), key=lambda item: str(item[0]))
        ],
        "diff": plan_result.diff,
    }


def _append_ndjson(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = JsonLogger.dumps(payload)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialized + "\n")


@app.command()
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True), default=Path("."))
@click.option("--policy", default="A", help="Conflict resolution policy")
def scan(repo: Path, policy: str) -> None:
    ensure_agents_md(repo)
    plan_data = _plan(repo, policy)
    click.echo(json.dumps(plan_data, ensure_ascii=False, indent=2))


def _print_plan(plan_data: dict) -> None:
    diff = plan_data.get("diff", "")
    if diff:
        click.echo(diff)
    else:
        click.echo("# no changes")
    click.echo(json.dumps({k: v for k, v in plan_data.items() if k != "diff"}, ensure_ascii=False, indent=2))


@app.command()
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True), default=Path("."))
@click.option("--policy", default="A", help="Conflict resolution policy")
def plan(repo: Path, policy: str) -> None:
    ensure_agents_md(repo)
    plan_data = _plan(repo, policy)
    _print_plan(plan_data)


@app.command()
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True), default=Path("."))
@click.option("--policy", default="A", help="Conflict resolution policy")
@click.option("--apply", is_flag=True, help="Apply the plan")
def fix(repo: Path, policy: str, apply: bool) -> None:
    ensure_agents_md(repo)
    plan_data = _plan(repo, policy)
    _print_plan(plan_data)
    if not apply:
        return
    clock = DeterministicClock()
    metrics = DoctorMetrics.fresh()
    applied = False
    for action in plan_data["actions"]:
        path = Path(action["file"])
        atomic_write(path, action["updated_text"], clock=clock)
        applied = True
    if applied:
        metrics.observe_fix()


@app.command()
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True), default=Path("."))
@click.option("--policy", default="A", help="Conflict resolution policy")
def verify(repo: Path, policy: str) -> None:
    ensure_agents_md(repo)
    plan_data = _plan(repo, policy)
    if plan_data["actions"]:
        click.echo(json.dumps(plan_data, ensure_ascii=False, indent=2))
        raise click.exceptions.Exit(1)
    click.echo(json.dumps({"status": "ok", "plan_id": plan_data["plan_id"]}, ensure_ascii=False))


@app.command()
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True), default=Path("."))
@click.option("--policy", default="A", help="Conflict resolution policy")
@click.option("--apply", is_flag=True, help="Apply the plan")
def all(repo: Path, policy: str, apply: bool) -> None:
    ensure_agents_md(repo)
    plan_data = _plan(repo, policy)
    _print_plan(plan_data)
    if apply:
        clock = DeterministicClock()
        metrics = DoctorMetrics.fresh()
        for action in plan_data["actions"]:
            path = Path(action["file"])
            atomic_write(path, action["updated_text"], clock=clock)
        if plan_data["actions"]:
            metrics.observe_fix()


if __name__ == "__main__":  # pragma: no cover
    app()
