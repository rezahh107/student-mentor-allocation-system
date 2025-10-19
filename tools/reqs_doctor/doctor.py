
from __future__ import annotations
import json, uuid, os
from pathlib import Path
import typer
from .planner import plan as build_plan
from .clock import DeterministicClock
from .io_utils import atomic_write
from .obs import DoctorMetrics, JsonLogger

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Requirements Doctor (minimal)")

def _append_ndjson(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(JsonLogger.dumps(payload) + "\n")

def _correlation_id(pid: str) -> str:
    return os.environ.get("X_REQUEST_ID") or pid or uuid.uuid4().hex

@app.command()
def plan(
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
    policy: str = typer.Option("A", help="Conflict policy (A: conservative)"),
) -> None:
    pr = build_plan(repo, policy=policy)
    DoctorMetrics.fresh().observe_plan()
    payload = {
        "correlation_id": _correlation_id(pr.plan_id),
        "plan_id": pr.plan_id,
        "policy": policy,
        "messages": pr.messages,
        "actions": [{ "file": str(p), "reasons": a.reasons } for p,a in sorted(pr.actions.items(), key=lambda x: str(x[0]))],
        "diff": pr.diff,
    }
    _append_ndjson(repo / "reports" / "reqs_doctor.ndjson", payload)
    # Print diff then JSON (without diff) similar to earlier CLI
    if pr.diff:
        typer.echo(pr.diff)
    else:
        typer.echo("# no changes")
    pr_serial = dict(payload); pr_serial.pop("diff", None)
    typer.echo(json.dumps(pr_serial, ensure_ascii=False, indent=2))

@app.command()
def fix(
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
    policy: str = typer.Option("A"),
    apply: bool = typer.Option(False, "--apply", help="Apply changes"),
) -> None:
    pr = build_plan(repo, policy=policy)
    if not apply:
        # Show planned changes
        typer.echo(pr.diff if pr.diff else "# no changes")
        return
    clock = DeterministicClock()
    metrics = DoctorMetrics.fresh()
    for p, a in pr.actions.items():
        atomic_write(p, a.updated_text, clock=clock)
    if pr.actions:
        metrics.observe_fix()
    typer.echo("✓ Applied {} change(s).".format(len(pr.actions)))

@app.command()
def verify(
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
    policy: str = typer.Option("A"),
) -> None:
    pr = build_plan(repo, policy=policy)
    if pr.actions:
        typer.echo(json.dumps({ "status": "needs_changes", "plan_id": pr.plan_id, "count": len(pr.actions)}, ensure_ascii=False))
        raise SystemExit(1)
    typer.echo(json.dumps({ "status": "ok", "plan_id": pr.plan_id }, ensure_ascii=False))

def main() -> int:
    return app()

if __name__ == "__main__":
    raise SystemExit(main())
