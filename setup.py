import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional


MIN_PYTHON = (3, 8)


def check_python_version() -> bool:
    """Ensure the interpreter meets the minimum supported version."""
    current = sys.version_info[:2]
    if current < MIN_PYTHON:
        print(
            f"⚠️ Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required (you have {current[0]}.{current[1]})"
        )
        return False
    return True


def set_pythonpath(project_root: Optional[Path] = None) -> str:
    """Set PYTHONPATH to the project root for the current process."""
    root = (project_root or Path.cwd()).resolve()
    os.environ["PYTHONPATH"] = str(root)
    print(f"✅ PYTHONPATH set to {root}")
    return os.environ["PYTHONPATH"]


def _install_from_requirements(requirements_file: str, label: str) -> bool:
    path = Path(requirements_file)
    if not path.exists():
        print(f"⚠️ {requirements_file} not found. Skipping {label} dependencies.")
        return True

    print(f"📦 Installing {label} dependencies from {requirements_file}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(path)],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"❌ Failed to install dependencies from {requirements_file}: {exc}")
        return False
    return True


def install_dependencies(advanced: bool = False, ml: bool = False) -> bool:
    """Install base and optional dependency groups."""
    ok = _install_from_requirements("requirements.txt", "base")
    if advanced and ok:
        ok = _install_from_requirements("requirements-advanced.txt", "advanced testing")
    if ml and ok:
        ok = _install_from_requirements("requirements-ml.txt", "ML")
    return ok


def setup_vscode_settings() -> None:
    """Create or update VS Code settings for a smoother workflow."""
    vscode_dir = Path(".vscode")
    vscode_dir.mkdir(exist_ok=True)

    settings_file = vscode_dir / "settings.json"
    settings: dict = {}
    if settings_file.exists():
        try:
            with settings_file.open("r", encoding="utf-8") as handle:
                settings = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"⚠️ Could not read existing VS Code settings ({exc}). Overwriting.")
            settings = {}

    settings.update(
        {
            "python.linting.enabled": True,
            "python.linting.pylintEnabled": True,
            "python.testing.pytestEnabled": True,
            "python.testing.unittestEnabled": False,
            "python.testing.nosetestsEnabled": False,
            "python.testing.pytestArgs": ["tests"],
            "python.envFile": "${workspaceFolder}/.env",
        }
    )

    with settings_file.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=4)

    print(f"✅ VSCode settings updated at {settings_file}")

    env_file = Path(".env")
    if not env_file.exists():
        env_file.write_text("PYTHONPATH=${workspaceFolder}\n", encoding="utf-8")
        print(f"✅ Created .env file at {env_file}")


def create_activation_scripts() -> None:
    """Create activation helper scripts for Windows and Unix shells."""
    windows_content = (
        "@echo off\n"
        "set PYTHONPATH=%CD%\n"
        "echo Environment activated. PYTHONPATH set to %CD%\n"
    )
    Path("activate.bat").write_text(windows_content, encoding="utf-8")

    posix_content = (
        "#!/bin/bash\n"
        "export PYTHONPATH=\"$(pwd)\"\n"
        "echo \"Environment activated. PYTHONPATH set to $(pwd)\"\n"
    )
    activate_sh = Path("activate.sh")
    activate_sh.write_text(posix_content, encoding="utf-8")

    try:
        current_mode = activate_sh.stat().st_mode
        activate_sh.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as exc:
        print(f"⚠️ Could not mark activate.sh as executable: {exc}")

    print("✅ Created activation scripts (activate.bat and activate.sh)")


def main() -> int:
    print("🚀 Setting up testing environment...")

    if not check_python_version():
        return 1

    try:
        advanced = input("Install advanced testing dependencies? (y/N): ").strip().lower() == "y"
        ml = input("Install ML dependencies for prediction features? (y/N): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        print("\n⚠️ Setup cancelled by user input.")
        return 1

    if not install_dependencies(advanced, ml):
        print("❌ Dependency installation failed. Resolve the issues above and re-run setup.")
        return 1

    set_pythonpath()
    setup_vscode_settings()
    create_activation_scripts()

    print("\n🎉 Setup complete! You can now run tests with:")
    print("  - VS Code: F1 > 'Tasks: Run Task' > Select test task")
    print("  - Terminal: make test-quick or python test_runner.py --mode quick")
    print("\nTo activate the environment in a new terminal:")
    if platform.system() == "Windows":
        print("  - Run: activate.bat")
    else:
        print("  - Run: source ./activate.sh")

    return 0


if __name__ == "__main__":
    sys.exit(main())
