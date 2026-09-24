# Architecture

## Overview

DecGuard is a Python 3.11+ CLI and library (`src/decguard/`) that tests probabilistic
decision models against a versioned Decision Contract and produces one canonical
reliability report with PASS / WARN / FAIL gates. It is backend-neutral: models are
reached through thin adapters that all normalize into the same `DecisionResult`.

The v0.1 plan is `state/DECGUARD_V0.1_CODEX_PLAN.md`. Step 1 (core, contracts, backends,
CLI) is implemented; fuzzing, regression, post-deploy checks and policies are not yet.

## Major components

- `contracts/`: schema `0.1` (`models.py`: `Contract`, `ChoiceDecision` / `NoulDecision` /
  `ScoreDecision`, `BackendConfig`, `Evaluation`, `Gates`) and loading (`loader.py`: safe
  YAML/JSON with duplicate-key rejection, `sha256:` hash of the normalized contract).
- `decisions/`: `DecisionSpec` (name, type, canonical label order), `DecisionRequest`,
  `Prediction` (raw backend output), `DecisionResult` (unified schema) and
  `validate_probabilities` (no silent repair).
- `datasets.py`: golden cases from JSONL/JSON (`id`, `input`, optional `expected`,
  `metadata`), validated against the contract labels; file hash.
- `backends/`: `DecisionBackend` base (`predict` implemented by adapters; shared `decide`,
  `metadata`, `healthcheck`, `close`), built-ins `mock` and `http`, `CallableBackend` (SDK
  only), and `registry.py` (built-ins + `decguard.backends` entry points).
- `runner.py`: runs cases with a bounded thread pool, keeps dataset order, turns
  `BackendError`s and unexpected plugin exceptions into per-case `CaseError`s; other
  `DecGuardError`s abort.
- `metrics/`: `core.py` pure stdlib metric functions; `summary.py` aggregates records into
  `Metrics` (counts, classification, calibration, selective, latency).
- `reports/`: `gates.py` (gate table, implicit `max_error_rate: 0`, status), `model.py`
  (`Report` JSON model, `build_report`, `reevaluate`, read/write), `render.py` (terminal).
- `engine.py`: `run_test()` orchestration shared by CLI and Python API.
- `cli/`: typer app with `validate`, `test`, `report`.

## Data flow

contract file → `load_contract` → `Contract` → `spec()` + `create_backend()`;
dataset file → `load_dataset` → cases; `run_cases` → `CaseRecord`s (result or error) →
`compute_metrics` → `evaluate_gates` → `Report` → JSON file / terminal text / exit code.
`decguard report --contract` re-runs the last three steps on stored records.

## External systems

- Decision backends over HTTP (`decguard.http/0.1`, docs/backends.md) or installed
  plugins. None is needed for the default test suite; a local stdlib HTTP server backs the
  integration tests. Real endpoints are opt-in (`pytest -m external`).
- GitHub Actions CI (`.github/workflows/ci.yml`).

## Important constraints

- Exit codes are API: 0 pass/warn, 1 gate failed, 2 configuration/runtime error
  (unexpected exceptions are mapped to 2, never 1).
- Malformed backend output and invalid dataset rows are errors, never repaired or dropped.
- Metrics are deterministic (`math.fsum`, dataset order); the mock backend's hash output is
  pinned by a test.
- Credentials only via environment variables; never in reports, errors or metadata.
- Contracts never execute code (safe YAML, no import paths).
- Runtime dependencies: pydantic, typer, httpx, PyYAML (see
  `decisions/core-dependencies-and-internal-metrics.md`).
