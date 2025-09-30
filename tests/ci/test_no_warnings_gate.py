from __future__ import annotations


def test_no_warnings(pytestconfig) -> None:
    filters = pytestconfig.getini("filterwarnings")
    assert filters == ["error"], filters
    scope = pytestconfig.getini("asyncio_default_fixture_loop_scope")
    assert scope == "function"
    assert pytestconfig.pluginmanager.has_plugin("pytest_asyncio")
