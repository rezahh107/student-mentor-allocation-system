import pytest


@pytest.mark.security
def test_rbac_placeholder():
    pytest.skip("RBAC enforcement not implemented in UI layer; to be tested in backend integration phase.")


@pytest.mark.security
def test_sensitive_data_handling_placeholder():
    pytest.skip("PII masking/encryption policy to be defined; logging reviewed to avoid stack traces.")

