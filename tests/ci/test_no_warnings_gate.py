from __future__ import annotations


def test_no_warnings(pytestconfig) -> None:
    filters = pytestconfig.getini("filterwarnings")
    assert filters == [
        "error",
        "ignore::DeprecationWarning",
        "ignore::PendingDeprecationWarning",
    ], filters
    mode = pytestconfig.getini("asyncio_mode")
    assert mode == "auto"
    addopts_raw = pytestconfig.getini("addopts")
    if isinstance(addopts_raw, str):
        addopts = addopts_raw.split()
    else:
        addopts = list(addopts_raw)
    assert "--strict-config" in addopts or pytestconfig.option.strict_config
    assert "--strict-markers" in addopts or pytestconfig.option.strict_markers
    assert pytestconfig.pluginmanager.has_plugin("pytest_asyncio") or pytestconfig.pluginmanager.has_plugin(
        "pytest_asyncio.plugin"
    )
