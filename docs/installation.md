---
description: Install the DecGuard CLI and Python library from PyPI or from source.
---

# Installation

DecGuard is a Python package with a command-line interface. It needs **Python 3.11 or
newer** and is tested on Linux and macOS with Python 3.11, 3.12 and 3.13.

## From PyPI

```bash
pip install decguard
```

Or install the CLI as an isolated tool with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install decguard
```

Check the installation:

```bash
decguard --version
```

```text
decguard 0.1.1
```

`decguard` with no arguments, or `decguard <command> --help`, lists the commands and their
options. Running `python -m decguard` is equivalent.

## Dependencies

DecGuard has four runtime dependencies: `pydantic`, `typer`, `httpx` and `PyYAML`. There
are no optional extras: the mock, HTTP and System One backends, metrics, fuzzing,
regression diffs, production checks and the SDK all ship in the base package. No GPU,
model weights, database or service account is required.

Backends that serve real models run wherever you run them. DecGuard only needs network
access to their URL and, when they require one, a credential in an
[environment variable](./backends.md#credentials).

## As a library

The same package provides the Python API used by the CLI:

```python
from decguard import DecGuard  # runtime policy SDK
from decguard.engine import run_test  # golden tests and fuzzing from Python
from decguard.backends import CallableBackend  # wrap a Python function as a backend
```

See [Policies and Python SDK](./policy.md) and [Custom backends](./custom-backends.md).

## From source

To try unreleased changes or contribute:

```bash
git clone https://github.com/suffro/decguard
cd decguard
uv tool install .           # or, inside a virtual environment: pip install .
```

For development (tests, linting, type checks), use the locked environment:

```bash
uv sync
uv run pytest
```

The repository's
[CONTRIBUTING.md](https://github.com/suffro/decguard/blob/main/CONTRIBUTING.md) describes
the full workflow.

## In CI

Install from PyPI in the job, pinning the version you tested with:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: pip install decguard==0.1.1
```

See [CI with GitHub Actions](./ci.md) for complete workflows.

Next: [write your first contract](./quickstart.md).
