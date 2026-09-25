---
name: python-project
description: Start or work on a Python project with a virtual environment, dependencies, tests and a runnable entry point
---

# Python projects

- New project: a folder in the workspace with `pyproject.toml` or `requirements.txt`, a package or
  `main.py`, and `tests/`.
- Always use a virtual environment in the project (Debian blocks `pip install` system-wide):
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. Run things with `.venv/bin/python`.
  If venv is missing, the `python3-venv` package provides it (PolyMarket's Developer pack installs it).
- Tests: `.venv/bin/python -m pytest -q` (install pytest into the venv first). Run them after each change.
- Read tracebacks from the bottom: the last line is the error, the lines above show where.
- Keep secrets (API keys, passwords) in environment variables or a `.env` file listed in `.gitignore`.
- GUI or long-running programs: start them with a timeout, or tell the person how to run them in a Terminal.
