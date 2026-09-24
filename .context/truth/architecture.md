# Architecture

## Overview

DecGuard is a Python 3.11+ CLI and library (`src/decguard/`) that tests probabilistic
decision models against a versioned Decision Contract and produces one canonical
reliability report with PASS / WARN / FAIL gates. It is backend-neutral: models are
reached through thin adapters that all normalize into the same `DecisionResult`.

The v0.1 plan is `state/DECGUARD_V0.1_CODEX_PLAN.md`. Steps 1 (core, contracts, backends,
CLI), 2 (metamorphic fuzzing, regression diff, replay) and 3 (offline production checks,
explicit policies and SDK) are implemented.

## Major components

- `contracts/`: schema `0.1` (`models.py`: `Contract`, `ChoiceDecision` / `NoulDecision` /
  `ScoreDecision`, `BackendConfig`, `Evaluation`, `Gates`; `properties.py`: `Properties`
  and one model per property, `Fuzz`, `Regression`) and loading (`loader.py`: safe
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
- `metrics/`: `core.py` pure stdlib metric functions; `distribution.py` TV / JS / max
  delta / expected level / ranking; `summary.py` aggregates records into `Metrics`.
- `fuzz/`: `rng.py` (SHA-256 stream per seed/property/case), `transforms.py` (pure,
  replayable step lists; option presentation as `(shown, label)` pairs), `paraphrase.py`
  (`identity`, `file`, `openai`, `decguard.paraphrasers` plugins), `compare.py`
  (`Comparison`, `judge`), `engine.py` (`PropertyRunner`: plan, execute, map shown labels
  back, compare, minimize), `replay.py` (re-send stored failures, regeneration check).
- `regression/diff.py`: `diff_reports` on matched case ids, `DiffReport`, regression gates.
- `production/`: strict production JSONL/JSON records, metrics, confidence/calibration drift,
  metadata segments, gates and the versioned `ProductionReport`; no backend is called.
- `policy/`: pure first-match evaluation of validated contract routes.
- `sdk.py`: `DecGuard.from_contract(...).decide(...)`, sharing backend normalization and the
  policy engine with CLI `run`.
- `reports/`: `gates.py` (gate table, `make_check`, implicit `max_error_rate: 0`, status),
  `model.py` (`Report` JSON model with `mode` and optional `properties`, `build_report`,
  `reevaluate`, read/write), `properties.py` (transformed-case records, summaries, property
  checks, `rejudge`, load-time `verify_run`), `render.py` (terminal).
- `engine.py`: `run_test(mode="test"|"fuzz"|"all")` orchestration shared by CLI and API.
- `cli/`: typer app with `validate`, `test` (`--all`), `fuzz`, `report`, `diff`, `replay`,
  offline `check`, and policy `run`.

## Data flow

contract file → `load_contract` → `Contract` → `spec()` + `create_backend()`;
dataset file → `load_dataset` → cases; `run_cases` → `CaseRecord`s (result or error) →
`compute_metrics` → `evaluate_gates` → `Report` → JSON file / terminal text / exit code.
`decguard report --contract` re-runs the last three steps on stored records.
Fuzz: after the golden run, each enabled property generates transformations per case →
`decide_mutation` (shown labels → backend → mapped back) → `compare`/`judge` against the
original → minimize failures → `PropertyRun` in the same `Report`.
Diff: two stored reports → matched cases → shifts, metric deltas, segments → gates.
Production: collected JSONL → strict normalization → aggregate/segment metrics → optional
dataset/report baseline drift → gates → production report. Runtime: backend result → ordered
policy → action directive (fallback is not invoked automatically).

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
- Fuzz runs are reproducible from the stored seed; transformation generation is pinned by
  tests (see `decisions/metamorphic-engine-design.md`).
- Runtime dependencies: pydantic, typer, httpx, PyYAML (see
  `decisions/core-dependencies-and-internal-metrics.md`).
