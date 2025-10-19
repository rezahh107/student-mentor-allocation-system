
from __future__ import annotations
import sys, pathlib
import typer

app = typer.Typer(add_completion=False, help="Repo Doctor CLI (safe wrapper)")

@app.command()
def scan() -> None:
    try:
        from src.repo_doctor import RepoDoctor  # type: ignore
        from src.repo_doctor.core import DoctorConfig  # type: ignore
        from src.repo_doctor.clock import tehran_clock  # type: ignore
    except Exception as e:
        typer.echo("⚠️ src.repo_doctor در ریپو موجود نیست یا ناقص است. این رابط امن فقط برای جلوگیری از خطای ImportError است.")
        raise SystemExit(2)
    root = pathlib.Path(__file__).resolve().parents[1]
    doctor = RepoDoctor(DoctorConfig(root=root, apply=False, clock=tehran_clock()))
    typer.echo(doctor.scan().as_dict())

@app.command()
def fix(apply: bool = typer.Option(False, "--apply")) -> None:
    try:
        from src.repo_doctor import RepoDoctor  # type: ignore
        from src.repo_doctor.core import DoctorConfig  # type: ignore
        from src.repo_doctor.clock import tehran_clock  # type: ignore
    except Exception:
        typer.echo("⚠️ src.repo_doctor در دسترس نیست. لطفاً ماژول‌های src را اضافه کنید یا فقط از tools.reqs_doctor استفاده کنید.")
        raise SystemExit(2)
    root = pathlib.Path(__file__).resolve().parents[1]
    doctor = RepoDoctor(DoctorConfig(root=root, apply=apply, clock=tehran_clock()))
    typer.echo(doctor.fix().as_dict())

def main() -> int:
    return app()

if __name__ == "__main__":
    raise SystemExit(main())
