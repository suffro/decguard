# Conventions

## Repository conventions

- Python 3.11+, `src/` layout, package `decguard`, managed with `uv` (`uv.lock` committed).
- Pydantic models for every external schema; user-facing models use `StrictModel`
  (`extra="forbid"`, frozen) so typos fail. Validation errors are rendered with
  `format_validation_error` as `path.to.field: message`.
- Errors raised on purpose derive from `decguard.errors.DecGuardError`; per-case backend
  failures derive from `BackendError` and carry a stable `kind`.
- Contract/report formats are versioned (`schema_version`, `report_version`, both `0.1`);
  changing their meaning requires a version bump and a CHANGELOG entry.
- Tests: `tests/unit/` (pure, fast) and `tests/integration/` (CLI, local HTTP server);
  shared fixtures in `tests/conftest.py`. Examples in `examples/` must pass `decguard
  test` and `decguard test --all` (`test_examples_pass`, `test_examples_pass_all_checks`).
- Deterministic outputs that users may store (mock hash distribution, fuzz RNG stream)
  are pinned by tests; changing them is a CHANGELOG-worthy format change.
- Docs for users in `docs/`; user-visible changes go in `CHANGELOG.md` under Unreleased.

## Development workflow

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

CI (`.github/workflows/ci.yml`) runs these on Ubuntu and macOS for Python 3.11–3.13 and
installs the built wheel in a clean environment.

## Important rules

- Never print or store secrets; credentials come from environment variables.
- Never silently repair backend output or skip dataset rows.
- Keep the core backend-neutral; new model families are adapters or plugins.
- Add a runtime dependency only with a recorded decision in `.context/decisions/`.
