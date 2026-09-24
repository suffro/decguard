# Current State

## Current focus

Building DecGuard v0.1 following `DECGUARD_V0.1_CODEX_PLAN.md` (this directory). Step 1
(core, contracts, backends, CLI) is implemented and committed; Step 2 (decision-specific
fuzzing, metamorphic testing, regression diff) is next.

## Recent relevant changes

- Step 1: contract schema 0.1 (choice/noul/score), unified `DecisionResult`, `mock` and
  `http` backends plus entry-point plugins and `CallableBackend`, golden datasets,
  metrics (accuracy, macro-F1, NLL, Brier, ECE, coverage, latency), requirement/warning
  gates, JSON + terminal reports, CLI `validate` / `test` / `report`, CI workflow, docs.

## Next

- Step 2 per the plan: metamorphic engine (option permutation first), distribution-aware
  comparisons, `decguard diff`, `fuzz`, `replay`, reproducible failure records.
- The contract schema currently rejects `properties`, `regression` and `policy` keys;
  add them (still schema `0.1` while unreleased) as Steps 2–3 implement them.

## Blockers

- CI has not yet run on GitHub: the Step 1 commit was verified locally only
  (Python 3.11 and 3.14 on macOS). Push to confirm the Linux/macOS matrix.
- No real Open-Jev/Kev endpoint or API description is available; only the generic
  HTTP protocol and the opt-in external test exist.
