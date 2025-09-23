# SmartAllocPY Environment Guide

## Quick Start
- Run `python setup.py` to install dependencies, set `PYTHONPATH`, configure VS Code, and generate `activate` scripts.
- Use `activate.bat` (Windows) or `source ./activate.sh` (macOS/Linux) before working in a new shell.
- Launch diagnostics with `python scripts/environment_doctor.py` to validate the environment and apply optional fixes.

## PYTHONPATH Management
- `setup.py` sets `PYTHONPATH` to the project root and updates `.env` for VS Code integrations.
- Activation scripts export `PYTHONPATH` for shell sessions; re-run them whenever you open a new terminal.
- The doctor script checks whether the project root is present in `PYTHONPATH` and can auto-fix common issues.

## Troubleshooting
- If dependencies are missing, re-run `python setup.py` and select the optional groups you need.
- Use `python -m compileall setup.py scripts/environment_doctor.py` to perform a quick syntax check before commits.
- When Docker is unavailable, install it from docker.com or update your PATH.

## Additional Resources
- `Makefile` provides shortcuts like `make test-quick` for CI-aligned test runs.
- For advanced analytics dashboards, run `streamlit run scripts/dashboard.py` after setup completes.

## Streamlit Dashboards
- Every dashboard module calls `configure_page()` immediately after imports so `st.set_page_config` executes before any other Streamlit command.
- When adding new Streamlit views, follow the same pattern: define a `configure_page()` helper, invoke it at module load, then render the UI in `main()` or a `run()` method.
- Remember that calling `st.set_page_config` after rendering UI elements triggers `StreamlitSetPageConfigMustBeFirstCommandError`.

