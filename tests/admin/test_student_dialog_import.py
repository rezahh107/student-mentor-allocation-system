"""Regression tests for importing the student dialog module."""

import importlib

import pytest


def test_admin_student_dialog_import() -> None:
    """Ensure the student dialog module imports without raising exceptions."""
    pytest.importorskip("PyQt5")
    module = importlib.import_module("src.ui.pages.dialogs.student_dialog")
    assert hasattr(module, "StudentDialog")
