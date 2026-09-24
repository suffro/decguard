# Current State

## Current focus

Building DecGuard v0.1 following `DECGUARD_V0.1_CODEX_PLAN.md` (this directory). Steps 1
and 2 are merged. Step 3 (offline post-deployment checks, explicit cascade policies and
SDK) is implemented on branch `step-3-production-policy` and awaiting review/merge.

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

## Next

- Complete review and merge of Step 3. Do not tag/publish v0.1 without the separate final
  release validation in the plan.

## Blockers

- No real Open-Jev/Kev endpoint or API description is available; only the generic HTTP
  protocol and the opt-in external test exist. The same holds for a real LLM paraphraser:
  the `openai` provider is tested against a mocked transport only.
