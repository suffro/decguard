# Contributing to DecGuard

Thanks for helping. DecGuard aims to stay small: a typed, deterministic core that owns
decision contracts, result normalization, reliability metrics, reports and CI semantics,
with everything else reused from existing tools or added as optional integrations.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
uv sync                      # create .venv with runtime + dev dependencies
uv run pytest                # tests (no network, GPU or paid service needed)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # strict type checking
```

CI runs the same commands on Linux and macOS for Python 3.11–3.13, plus a clean-install
check of the built wheel.

Tests that need a real decision backend are opt-in:

```bash
DECGUARD_EXTERNAL_CONTRACT=path/to/decguard.yaml uv run pytest -m external
```

## Guidelines

- **Never silently repair or drop data.** Malformed backend output is an error that is
  counted and reported; invalid dataset rows fail loading.
- **Keep results deterministic.** Metrics must be bit-reproducible for the same inputs; the
  mock backend's output is pinned by tests.
- **Security:** credentials only via environment variables, never printed or stored in
  reports; contracts and datasets are untrusted input and never execute code.
- **Dependencies:** add one only when it clearly beats a small internal implementation, and
  record the reason in `.context/decisions/`.
- **Exit codes are API:** 0 pass/warn, 1 reliability gate failed, 2 configuration/runtime
  error.
- Update `CHANGELOG.md` (Unreleased) and the docs with user-visible changes, and
  `.context/` when architecture or conventions change.

## Adding a backend

See [docs/backends.md](docs/backends.md). Built-in adapters live in
`src/decguard/backends/`; third-party ones should be separate packages registered under the
`decguard.backends` entry-point group.
