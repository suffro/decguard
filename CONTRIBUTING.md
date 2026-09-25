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

## Releasing

A pushed `vX.Y.Z` tag is the release. To cut one:

1. Make sure CI is green on `main`.
2. Make sure the `Real backends` workflow (Kev and Jev, Ubuntu and macOS) is green on the
   commit you will tag (`gh workflow run real-backends.yml --ref main`).
3. Make sure `pyproject.toml` has `version = "X.Y.Z"` and `CHANGELOG.md` has a
   `## [X.Y.Z] - <date>` section.
4. Tag that commit and push the tag:

   ```bash
   git tag vX.Y.Z <commit>
   git push origin vX.Y.Z
   ```

5. `.github/workflows/release.yml` then runs build → PyPI → GitHub Release:
   - **build** checks that the tag is `vX.Y.Z`, matches the package version, has a
     CHANGELOG section, points at the checked-out commit and has no GitHub Release yet.
     It then runs lint, `mypy` and the test suite, builds the wheel and sdist once, checks
     them (`twine check --strict`, the sdist builds), and smoke-tests the wheel in a clean
     environment.
   - **publish** uploads exactly those files to PyPI after verifying their SHA-256
     digests.
   - **github-release** creates the release for the tag, with generated notes and the same
     two files. It only runs if the PyPI upload succeeded.

   If any check fails, nothing is published. Fix it on `main` and release a new version;
   PyPI never accepts the same version twice.

The workflow uses PyPI Trusted Publishing (OIDC), so no PyPI token or password is stored
anywhere. The one required setup is on PyPI: a trusted publisher for the `decguard` project
(a *pending* publisher before the first upload) with owner `suffro`, repository `decguard`,
workflow `release.yml` and environment `pypi`.

GitHub creates the `pypi` environment on the first run. Optionally, harden it in
Settings → Environments → `pypi`:

- Limit deployments to `v*.*.*` tags, so a modified `release.yml` pushed to a branch cannot
  publish.
- Add required reviewers, so every upload waits for a manual approval.

The release workflow never receives `OPENROUTER_API_KEY` or any other repository secret, and
does not run the paid real-backend tests.

## Adding a backend

See [docs/backends.md](docs/backends.md). Built-in adapters live in
`src/decguard/backends/`; third-party ones should be separate packages registered under the
`decguard.backends` entry-point group.
