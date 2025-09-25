import importlib


def test_cli_package_importable() -> None:
    module = importlib.import_module("src.cli")
    assert hasattr(module, "__all__")
