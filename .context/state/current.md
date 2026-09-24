# Current State

## Current focus

Final v0.1 release validation following `DECGUARD_V0.1_CODEX_PLAN.md` (this directory).
Steps 1–3 are merged. Release hardening is in progress on branch
`v0.1-release-validation`; do not tag or publish until it is merged and the real-backend
blocker below is cleared.

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
  the wheel metadata is `0.1.0`; the runnable demo covers calibration, regression and
  production drift.
- Local release checks pass: lint/format/type checks, 276 tests (the external test is the
  one intentional skip), the complete 0/1/2 workflow, and clean-wheel smoke on Python
  3.11, 3.12 and 3.13. Runtime dependency metadata contains only compatible permissive
  licenses plus Certifi's MPL-2.0; `uv.lock` is current and every registry artifact is
  hash-pinned.

## Next

- Complete PR review and the Linux/macOS CI matrix.
- Then run the opt-in real-backend test before tagging. Do not publish or tag from the
  validation branch.

## Blockers

- The sole release blocker is one successful opt-in call to a real decision backend. It
  requires either a reachable endpoint implementing `decguard.http/0.1`, or an installed
  plugin/proxy translating a real TypeSafe/Kev-style `POST /v1/systemone` service to that
  protocol, plus environment-provided credentials where required. Run it with
  `DECGUARD_EXTERNAL_CONTRACT=/absolute/path/to/contract uv run pytest -m external`.
