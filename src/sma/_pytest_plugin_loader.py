"""Helpers to dynamically resolve real pytest plugins when installed."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable, Sequence

from importlib.resources.abc import Traversable
from importlib.metadata import PackagePath

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _candidate_entries() -> Iterable[str]:
    for entry in list(sys.path):
        if not entry:
            continue
        try:
            path = Path(entry).resolve()
        except Exception:
            continue
        try:
            if path == _PROJECT_ROOT or _PROJECT_ROOT in path.parents:
                continue
        except RuntimeError:
            continue
        yield str(path)


def _load_from_spec(name: str, spec) -> ModuleType | None:
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        return None
    return module


def _load_from_traversable(
    name: str,
    resource: Traversable,
    *,
    package: bool,
) -> ModuleType | None:
    try:
        loader = importlib.machinery.SourceFileLoader(name, os.fspath(resource))
    except TypeError:
        # Fallback for Traversable objects without concrete fspath support.
        class _TraversableLoader(importlib.machinery.SourceLoader):
            def __init__(self, fullname: str, traversable: Traversable):
                self._fullname = fullname
                self._traversable = traversable

            def get_filename(self, fullname: str) -> str:  # pragma: no cover - trivial
                if fullname != self._fullname:
                    raise ImportError(fullname)
                return os.fspath(self._traversable)

            def get_data(self, path: str) -> bytes:  # pragma: no cover - trivial
                del path
                return self._traversable.read_bytes()

        loader = _TraversableLoader(name, resource)

    spec = importlib.util.spec_from_loader(
        name,
        loader,
        origin=os.fspath(resource),
        is_package=package,
    )
    if spec is None:
        return None
    if package:
        try:
            parent = resource.parent
            spec.submodule_search_locations = [os.fspath(parent)]
        except Exception:  # pragma: no cover - Traversable edge cases
            spec.submodule_search_locations = []
    return _load_from_spec(name, spec)


def _metadata_candidates(name: str) -> Sequence[tuple[Traversable, bool]]:
    module_parts = name.split(".")
    candidates: list[tuple[Traversable, bool]] = []
    try:
        package_paths: list[PackagePath] = []
        if module_parts:
            package_paths.append(PackagePath(*module_parts, "__init__.py"))
        package_paths.append(PackagePath(*module_parts).with_suffix(".py"))
        for dist in importlib_metadata.distributions():
            files = getattr(dist, "files", None)
            if not files:
                continue
            for relative in package_paths:
                if relative not in files:
                    continue
                try:
                    traversable = dist.locate_file(relative)
                except Exception:
                    continue
                candidates.append((traversable, relative.name == "__init__.py"))
    except Exception:
        return ()
    return candidates


def load_real_plugin(name: str, *, current_module: ModuleType) -> ModuleType | None:
    """Attempt to load the real plugin module if it is installed on sys.path."""

    previous = sys.modules.get(name)
    if previous is current_module:
        sys.modules.pop(name, None)
    else:
        previous = None

    try:
        for entry in _candidate_entries():
            spec = importlib.machinery.PathFinder.find_spec(name, [entry])
            module = _load_from_spec(name, spec)
            if module is not None:
                return module

        for traversable, is_package in _metadata_candidates(name):
            module = _load_from_traversable(name, traversable, package=is_package)
            if module is not None:
                return module
    finally:
        if name not in sys.modules:
            if previous is not None:
                sys.modules[name] = previous
            else:
                sys.modules[name] = current_module

    return None


__all__ = ["load_real_plugin"]
