"""Plugin shim that defers to pytest-xdist when available."""

from __future__ import annotations

import argparse
import sys
from typing import Final

from _pytest_plugin_loader import load_real_plugin


_CURRENT = sys.modules[__name__]
_REAL = load_real_plugin(__name__, current_module=_CURRENT)

if _REAL is not None:
    for attribute in ("__file__", "__spec__", "__loader__", "__package__"):
        if hasattr(_REAL, attribute):
            setattr(_CURRENT, attribute, getattr(_REAL, attribute))
    _CURRENT.__dict__.update({k: v for k, v in _REAL.__dict__.items() if k not in {"__name__"}})
    STUB_ACTIVE: Final[bool] = False
else:
    STUB_ACTIVE: Final[bool] = True

    def pytest_addoption(parser):  # pragma: no cover - option wiring only
        group = parser.getgroup("xdist-stub")
        group.addoption(
            "--numprocesses",
            dest="numprocesses",
            action="store",
            default="0",
            help="xdist stub: parallelism disabled; value ignored.",
        )
        # pytest 8+ reserves lowercase short options for core use when options
        # are registered via OptionGroup.addoption (shortupper=False).  The
        # real pytest-xdist plugin still exposes ``-n`` so we provide it via the
        # helper that skips the restriction.  Falling back to parser-level
        # registration keeps behaviour consistent even if internals change.
        try:
            group._addoption(  # type: ignore[attr-defined]
                "-n",
                dest="numprocesses",
                action="store",
                default="0",
                help=argparse.SUPPRESS,
            )
        except ValueError:
            parser.addoption(
                "-n",
                dest="numprocesses",
                action="store",
                default="0",
                help=argparse.SUPPRESS,
            )
        group.addoption(
            "--dist",
            dest="dist",
            action="store",
            default="no",
            help="xdist stub: distribution strategy ignored.",
        )

    def pytest_configure(config):  # pragma: no cover - prevents worker bootstrap
        config.option.numprocesses = "0"
        config.option.dist = "no"
