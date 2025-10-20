"""Repo Doctor package orchestrating repository remediation tasks.

The package purposely lives under :mod:`src` so that the import fixer can
exercise against a realistic tree.  All public APIs lean on deterministic
components (clock, retry, metrics) to satisfy the repository's agent
expectations documented in ``AGENTS.md``.
"""
from __future__ import annotations

from .clock import Clock, FrozenClock, tehran_clock
from .core import RepoDoctor

__all__ = ["RepoDoctor", "Clock", "FrozenClock", "tehran_clock"]
