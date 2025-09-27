"""Deterministic stub for python-multipart used in tests."""

__all__ = ["__version__", "parse_options_header"]

__version__ = "0.1.0"

from .multipart import parse_options_header  # noqa: E402,F401
