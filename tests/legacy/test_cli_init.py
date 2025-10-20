import importlib


def test_cli_package_importable() -> None:
    module = importlib.import_module("sma.cli")
    assert hasattr(module, "__all__")
