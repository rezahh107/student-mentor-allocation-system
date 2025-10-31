"""Re-export CLI helpers from the local tooling package."""
from importlib import import_module
from types import ModuleType

_cli: ModuleType = import_module("sma._local_tools.cli")
__all__ = getattr(_cli, "__all__", [])


def __getattr__(name: str) -> object:  # pragma: no cover - passthrough
    return getattr(_cli, name)


def __dir__() -> list[str]:  # pragma: no cover - passthrough
    return sorted(set(__all__) | set(dir(_cli)))
