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
- Docs for users in `docs/`, a VitePress site: every page is listed in the sidebar in
  `docs/.vitepress/config.mts`; links between pages are relative `.md` links so they work
  on GitHub too. The implementation is authoritative: command output shown in the docs is
  copied from real runs. User-visible changes go in `CHANGELOG.md` under Unreleased.
- The docs' production origin is `https://decguard.com` (the `hostname` const in
  `docs/.vitepress/config.mts`; also hard-coded in `docs/public/robots.txt`). It feeds the
  sitemap, canonical links and the Markdown surface. Deployment is not configured (no `base`,
  no workflow, no clean URLs: pages are `/name.html`).
- The docs build writes a Markdown twin of each page at its source path, plus `llms.txt` and
  `llms-full.txt` (`docs/.vitepress/llms.mjs`, from the `sidebar` const in `config.mts`),
  with absolute links on the production origin. Each page advertises its twin with
  `<link rel="alternate" type="text/markdown">`, which `theme/PageActions.vue` (the
  Markdown / Ask an AI buttons in the `doc-before` slot) reads. Twins exist only after
  `npm run build`: test those buttons with `npm run preview`, not `npm run dev`.
- Logos: `docs/public/static/svg/logo-{dark,light}.svg` (dark mark for light backgrounds),
  `docs/public/static/svg/favicon.svg` (same mark, adapts to the color scheme) and
  `docs/public/favicon.ico`.
- `README.md` is also the PyPI project page: link with absolute GitHub URLs, not
  repository-relative paths.

## Development workflow

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

Documentation (Node.js 18+, dev-only):

```bash
cd docs
npm ci
npm run dev      # local preview
npm run build    # production build into docs/.vitepress/dist; fails on dead links
```

CI (`.github/workflows/ci.yml`) runs these on Ubuntu and macOS for Python 3.11–3.13 and
installs the built wheel in a clean environment.

Real-backend checks are opt-in and never part of the default run (docs/systemone.md):
`uv run pytest -m real_kev` (a Kev server on 127.0.0.1:8009) and
`uv run pytest -m real_jev` (`OPENROUTER_API_KEY`). Once selected, a missing prerequisite
is a failure, not a skip. In CI they run only in `.github/workflows/real-backends.yml`.

## Important rules

- Never print or store secrets; credentials come from environment variables.
- Never silently repair backend output or skip dataset rows.
- Keep the core backend-neutral; new model families are adapters or plugins.
- Add a runtime dependency only with a recorded decision in `.context/decisions/`.
