from __future__ import annotations

import os
from pathlib import Path

import importlib

import scripts.guard_pythonpath as guard_pythonpath


def _reset_guard_module() -> None:
    importlib.reload(guard_pythonpath)


def test_guard_rejects_front_loaded_repo_path(monkeypatch, capsys):
    repo_root = Path(__file__).resolve().parents[2]
    bad_path = str(repo_root / "src")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([bad_path, "/opt/site-packages"]))

    exit_code = guard_pythonpath.main()
    captured = capsys.readouterr()

    assert exit_code == 1, "انتظار داشتیم نگهبان در برابر PYTHONPATH نامعتبر شکست بخورد."
    assert "خطا: مقدار PYTHONPATH نباید مسیر مخزن یا src را قبل از site-packages قرار دهد." in captured.err


def test_guard_allows_clean_pythonpath(monkeypatch, capsys):
    _reset_guard_module()
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join([
            "/usr/lib/python3.11/site-packages",
            "/opt/extras",
        ]),
    )

    exit_code = guard_pythonpath.main()
    captured = capsys.readouterr()

    assert exit_code == 0, "نگهبان باید PYTHONPATH سالم را بپذیرد."
    assert "PYTHONPATH بررسی شد؛ ترتیب مسیرها مجاز است." in captured.out
