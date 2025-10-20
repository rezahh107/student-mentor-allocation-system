
from __future__ import annotations

import json
import os
import pathlib
import sys

import typer

app = typer.Typer(add_completion=False, help="Repo Doctor CLI (safe wrapper)")
CORRELATION_ID = os.environ.get("SMA_CORRELATION_ID", "repo-doctor")


def emit(level: str, event: str, message: str, *, data: dict | None = None, err: bool = False) -> None:
    payload = {
        "level": level,
        "event": event,
        "message": message,
        "correlation_id": CORRELATION_ID,
    }
    if data is not None:
        payload.update(data)
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True), err=err)


@app.command()
def scan() -> None:
    try:
        from sma.repo_doctor import RepoDoctor  # type: ignore
        from sma.repo_doctor.core import DoctorConfig  # type: ignore
        from sma.repo_doctor.clock import tehran_clock  # type: ignore
    except Exception:
        emit(
            "error",
            "repo_doctor_missing",
            "خطا: ماژول sma.repo_doctor در ریپو موجود نیست یا ناقص است.",
            err=True,
        )
        raise SystemExit(2)
    root = pathlib.Path(__file__).resolve().parents[1]
    doctor = RepoDoctor(DoctorConfig(root=root, apply=False, clock=tehran_clock()))
    emit("info", "repo_doctor_scan", "اجرای RepoDoctor.scan تکمیل شد.", data={"result": doctor.scan().as_dict()})


@app.command()
def fix(apply: bool = typer.Option(False, "--apply")) -> None:
    try:
        from sma.repo_doctor import RepoDoctor  # type: ignore
        from sma.repo_doctor.core import DoctorConfig  # type: ignore
        from sma.repo_doctor.clock import tehran_clock  # type: ignore
    except Exception:
        emit(
            "error",
            "repo_doctor_unavailable",
            "خطا: ماژول sma.repo_doctor در دسترس نیست. لطفاً بستهٔ first-party را نصب کنید.",
            err=True,
        )
        raise SystemExit(2)
    root = pathlib.Path(__file__).resolve().parents[1]
    doctor = RepoDoctor(DoctorConfig(root=root, apply=apply, clock=tehran_clock()))
    emit(
        "info",
        "repo_doctor_fix",
        "اجرای RepoDoctor.fix تکمیل شد.",
        data={"apply": apply, "result": doctor.fix().as_dict()},
    )


def main() -> int:
    return app()


if __name__ == "__main__":
    raise SystemExit(main())
