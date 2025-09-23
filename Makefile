.PHONY: test-quick test-standard test-deep test-security test-full dashboard security-dashboard

PYTHON ?= python3

export PYTHONPATH := 272(CURDIR)

test-quick:
	272(PYTHON) -m scripts.adaptive_testing --mode=quick

test-standard:
	272(PYTHON) -m scripts.adaptive_testing --mode=standard

test-deep:
	272(PYTHON) -m scripts.adaptive_testing --mode=deep

test-security:
	272(PYTHON) -m scripts.adaptive_testing --mode=security

test-full:
	272(PYTHON) -m scripts.adaptive_testing --mode=full

dashboard:
	272(PYTHON) -m streamlit run scripts/dashboard.py

security-dashboard:
	272(PYTHON) -m streamlit run scripts/security_dashboard.py
