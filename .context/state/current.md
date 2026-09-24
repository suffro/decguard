# Current State

## Current focus

Building DecGuard v0.1 following `DECGUARD_V0.1_CODEX_PLAN.md` (this directory). Step 1
is merged (PR #1). Step 2 (metamorphic fuzzing, regression diff, replay, CI) is
implemented on branch `step-2-fuzzing`. Step 3 (post-deployment checks, cascade policies,
SDK) is next.

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

## Next

- Step 3 per the plan: offline analysis of production JSONL, calibration drift gates,
  segmentation, explicit policy engine (accept/abstain/fallback/review), Python SDK.
- The contract schema still rejects `policy`; add it (schema `0.1` while unreleased).

## Blockers

- No real Open-Jev/Kev endpoint or API description is available; only the generic HTTP
  protocol and the opt-in external test exist. The same holds for a real LLM paraphraser:
  the `openai` provider is tested against a mocked transport only.
