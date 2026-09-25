# Current State

## Current focus

`0.1.0` is released: tag `v0.1.0` on `ca2373a`, published to PyPI by `release.yml`
(Trusted Publishing, attestations) with the same wheel and sdist on the GitHub Release.
The repository is public. `0.1.1` (on `main`, not yet tagged) only fixes the README, which
is the PyPI project page: install with `pip install decguard`, absolute GitHub links.

## Recent relevant changes

- Step 1: contract schema 0.1, unified `DecisionResult`, `mock`/`http`/plugin backends,
  golden datasets, metrics, gates, JSON + terminal reports, CLI `validate`/`test`/`report`,
  persisted-report invariants, CI.
- Step 2: contract `properties`/`fuzz`/`regression` sections; eight properties
  (option order, label format, irrelevant/repeated context, whitespace, paraphrase, noul
  inversion, score monotonicity); distribution-aware comparisons; deterministic SHA-256
  seeding; greedy minimization; paraphrase providers; CLI `fuzz`, `test --all`, `replay`,
  `diff`; report `mode` + `properties` section with load-time integrity checks; mock
  `position_bias`; examples with properties; CI demonstrates a failing property.
- Step 3: backend-neutral production records; offline `check` reports with calibration,
  threshold/routing/confidence/latency/cost metrics; baseline drift; metadata segments and
  gates; deterministic `policy` routes; CLI `run`; minimal `DecGuard` Python SDK; CI smoke.
- Release validation: canonical reports now recompute and verify counts, metrics, failures,
  property summaries, checks and status on load; HTTP error bodies are not persisted,
  authenticated healthchecks cannot cross origins, and secret-like metadata is redacted;
  the runnable demo covers calibration, regression and
  production drift.
- Real backends: built-in `systemone` backend (TypeSafe System One wire format) for Kev,
  Jev and OpenRouter's Decisions API; opt-in `real_kev` / `real_jev` tests
  (`tests/integration/test_real_backends.py`, contracts in `tests/integration/real/`); the
  manual `Real backends` workflow (Ubuntu + macOS, Python 3.13). Pinned: Kev commit
  `09ff745d52a0`, checkpoint `jaredpalmer/kev-0.8b@9a45d25eb2ab`, Jev `typesafe/jev-1.13`
  (served as `typesafe/jev-1.13-20260917`).
- Local release checks pass: lint/format/type checks, 313 tests (8 intentional opt-in
  skips: `external`, `real_kev`, `real_jev`), the complete 0/1/2 workflow, and clean-wheel
  smoke. Earlier validation covered Python 3.11, 3.12 and 3.13. Runtime dependency
  metadata contains only compatible permissive licenses plus Certifi's MPL-2.0; `uv.lock`
  is current and every registry artifact is hash-pinned. No runtime dependency was added
  for the real backends.
- Release workflow: pushing a `vX.Y.Z` tag validates the tag against `pyproject.toml` and
  CHANGELOG, builds and checks the distributions once, publishes them to PyPI with Trusted
  Publishing (environment `pypi`, no stored token), then creates the GitHub Release with
  the same files. Procedure in CONTRIBUTING.md#releasing.

## Next

- Release `0.1.1` (push `v0.1.1` on the `main` commit with the README fix) so PyPI shows the
  corrected page; a released version's PyPI description cannot be edited.

## Blockers

- None. The PyPI trusted publisher (`suffro`/`decguard`, `release.yml`, environment `pypi`)
  is configured. To re-run the real-backend check, dispatch `real-backends.yml` (it needs
  the repository secret `OPENROUTER_API_KEY`).
