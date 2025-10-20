from pathlib import Path


SCRIPT_PATH = Path("tools/win/diagnose.ps1")


def test_diagnose_script_includes_prerequisite_checks():
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    expected_snippets = [
        "Get-Command py",
        "Python 3.11 یافت نشد یا قابل اجرا نیست.",
        "git config --get $Key",
        "core.autocrlf",
        "core.longpaths",
        "OutputEncoding",
        "خروجی PowerShell روی UTF-8 تنظیم است.",
        "PowerShell باید حداقل نسخهٔ ۷٫۴ باشد.",
        "اجرای اسکریپت به اتصال اینترنت نیاز ندارد.",
    ]
    for snippet in expected_snippets:
        assert snippet in text, f"'{snippet}' باید در اسکریپت تشخیصی موجود باشد"
