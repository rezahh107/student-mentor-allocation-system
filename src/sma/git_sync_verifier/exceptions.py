"""Custom exceptions for sync verifier."""

from __future__ import annotations


class SyncProcessError(RuntimeError):
    """Wrap an error with exit code and status."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int,
        status: str,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.status = status
        self.context = context or {}


class GitCommandError(RuntimeError):
    """Raised when a git command fails."""

    def __init__(self, command: list[str], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        display = " ".join(command)
        super().__init__(f"git command failed: {display} ({returncode})")
