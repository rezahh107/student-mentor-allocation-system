from __future__ import annotations

from pathlib import Path

from tools import ci_bootstrap


class _Result:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0


def test_auto_flow_validates_remote_and_invokes_rerun(clean_state, monkeypatch, tmp_path):
    repo_root = tmp_path / "repo-auto"
    repo_root.mkdir()

    calls: list[list[str]] = []

    def fake_git(args: list[str], cwd: Path) -> _Result:
        calls.append(args)
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return _Result(stdout="main")
        if args[:2] == ["status", "--porcelain"]:
            return _Result(stdout="")
        return _Result(stdout="ok")

    monkeypatch.setattr(ci_bootstrap, "_git", fake_git)
    monkeypatch.setattr(ci_bootstrap, "gha_rerun", type("_R", (), {"run": staticmethod(lambda argv: 0)}))

    ci_bootstrap._auto_flow(repo_root, "ci/runner-matrix-1", "ci.yml", "origin")

    assert ["remote", "get-url", "origin"] in calls, f"باید ریموت بررسی شود: {calls}"
    assert ["push", "--dry-run", "origin", "HEAD:ci/runner-matrix-1"] in calls, "dry-run push باید انجام شود"
    assert any(cmd[:2] == ["checkout", "-b"] for cmd in calls), f"ساخت شاخه جدید انجام نشد: {calls}"


def test_bootstrap_auto_reports_remote_failure(clean_state, monkeypatch, tmp_path, capsys):
    repo_root = tmp_path / "repo-fail"
    repo_root.mkdir()

    monkeypatch.setattr(ci_bootstrap, "_run_patcher", lambda *a, **k: 0)
    monkeypatch.setattr(ci_bootstrap, "_has_changes", lambda *a, **k: True)
    monkeypatch.setattr(ci_bootstrap, "_ensure_git_available", lambda: None)
    monkeypatch.setattr(ci_bootstrap, "_ensure_clean_worktree", lambda _root: None)

    def fake_auto_flow(*_args, **_kwargs):
        raise ci_bootstrap._perr(
            "GIT_REMOTE_INVALID",
            "دسترسی push به ریموت origin تأیید نشد (boom)",
        )

    monkeypatch.setattr(ci_bootstrap, "_auto_flow", fake_auto_flow)
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    rc = ci_bootstrap.run([str(repo_root), "--auto"])
    assert rc == 1, "باید در خطای ریموت کد خطا بازگردد"
    err = capsys.readouterr().err
    assert "GIT_REMOTE_INVALID" in err, f"پیام خطا باید شامل کد باشد: {err}"


def test_bootstrap_git_not_found(clean_state, monkeypatch, tmp_path, capsys):
    repo_root = tmp_path / "repo-missing-git"
    repo_root.mkdir()

    def raise_git_missing() -> None:
        raise ci_bootstrap._perr("GIT_NOT_FOUND", "git موجود نیست")

    monkeypatch.setattr(ci_bootstrap, "_ensure_git_available", raise_git_missing)

    rc = ci_bootstrap.run([str(repo_root)])
    assert rc == 1, "نبود git باید با خطا خاتمه یابد"
    err = capsys.readouterr().err
    assert "GIT_NOT_FOUND" in err, f"باید پیام git نبودن را گزارش کند: {err}"


def test_bootstrap_detects_dirty_tree(clean_state, monkeypatch, tmp_path, capsys):
    repo_root = tmp_path / "repo-dirty"
    repo_root.mkdir()

    monkeypatch.setattr(ci_bootstrap, "_ensure_git_available", lambda: None)
    def raise_dirty(_: Path) -> None:
        raise ci_bootstrap._perr("GIT_DIRTY", "شاخه کثیف است")

    monkeypatch.setattr(ci_bootstrap, "_ensure_clean_worktree", raise_dirty)

    rc = ci_bootstrap.run([str(repo_root)])
    assert rc == 1, "شاخه کثیف باید خطا دهد"
    err = capsys.readouterr().err
    assert "GIT_DIRTY" in err, f"باید پیام شاخه کثیف را نمایش دهد: {err}"
