from pathlib import Path


GUIDE_PATH = Path("docs/windows-powershell-setup.md")
CHECKLIST_PATH = Path("docs/windows-onboarding-checklist.md")
README_PATH = Path("README.md")


def test_windows_guide_contains_required_commands():
    text = GUIDE_PATH.read_text(encoding="utf-8")
    required_snippets = [
        "pip install -e .[dev]",
        "Start-App.ps1",
        "AGENTS.md::8 Testing & CI Gates",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q `",
        "پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.",
    ]
    for snippet in required_snippets:
        assert snippet in text, f"'{snippet}' باید در سند ویندوز وجود داشته باشد"


def test_readme_links_to_windows_guide():
    text = README_PATH.read_text(encoding="utf-8")
    assert "docs/windows-powershell-setup.md" in text, "README باید به راهنمای ویندوز لینک داشته باشد"


def test_checklist_covers_key_steps():
    text = CHECKLIST_PATH.read_text(encoding="utf-8")
    expected = [
        "py -3.11 -m venv .venv",
        "python -m pip install -U pip setuptools wheel",
        "python scripts/verify_agents.py",
        "python scripts/guard_pythonpath.py",
        "pwsh -File .\\Start-App.ps1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q `",
        "pwsh -File .\\tools\\win\\diagnose.ps1",
        "پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.",
    ]
    for snippet in expected:
        assert snippet in text, f"'{snippet}' باید در چک‌لیست ثبت شود"
