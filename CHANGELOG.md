# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may break
compatibility; the contract (`schema_version`) and report (`report_version`) formats are
versioned separately.

## [Unreleased]

### Added

- Decision Contract schema `0.1` for `choice`, `noul` (boolean) and `score` (ordered)
  decisions, with strict validation, duplicate-key detection and a stable contract hash.
- Unified `DecisionResult` schema; backend probabilities are validated (finite,
  non-negative, normalized within tolerance, exact label set) and never repaired.
- `DecisionBackend` interface (`decide`, `metadata`, `healthcheck`) with a deterministic
  `mock` backend, a generic `http` backend (`decguard.http/0.1` protocol, env-based
  credentials, safe retries, label mapping), a `CallableBackend` for Python code, and
  third-party providers via the `decguard.backends` entry-point group.
- Golden datasets in JSONL/JSON with optional expected labels and metadata.
- Metrics: accuracy, macro-F1, per-label scores, ordinal MAE (score), NLL, Brier, ECE with
  reliability bins, coverage/abstention/selective accuracy, error counts, latency
  percentiles.
- Requirement (fail) and warning gates; canonical JSON report and terminal rendering.
  Stored reports are re-validated on load: each result must be a valid distribution
  (within the recorded tolerance) whose `selected`/`confidence` match the argmax, and each
  case must hold exactly one of `result` or `error`.
- CLI: `decguard validate`, `decguard test`, `decguard report` (with re-evaluation against
  an edited contract). Exit codes: 0 pass/warn, 1 gate failed, 2 configuration/runtime
  error.
- Metamorphic properties (contract `properties` and `fuzz` sections):
  - `option_order`, `label_format`, `irrelevant_context`, `repeated_context`, `whitespace`
    and `paraphrase`;
  - noul `inversion` (the answer must swap);
  - score `monotonic` (the score must not move against a declared direction).

  Transformed options are sent as shown and mapped back to contract labels.
- Distribution-aware comparisons: total variation distance, Jensen-Shannon divergence, max
  absolute delta, confidence delta, answer flip, rank change, expected-level delta. Limits
  apply per transformed case, plus aggregate violation and flip rates, at requirement or
  warning level.
- Deterministic fuzzing:
  - a SHA-256 random stream keyed by (seed, property, case id);
  - greedy minimization of failing transformations;
  - untransformable cases are recorded with a reason, never dropped.
- Paraphrase providers: `identity`, `file` (curated JSONL), `openai` (OpenAI-compatible,
  optional), plus plugins via the `decguard.paraphrasers` entry-point group.
- Reports gain `mode` (`test`/`fuzz`/`all`) and a `properties` section. On load, stored
  comparisons and violations are checked against their results and recorded settings.
  `decguard report --contract` re-applies edited property limits.
- `decguard fuzz`, `decguard test --all`, `decguard replay` (re-sends stored failures,
  checks the seed regenerates them, exit 1 if reproduced) and `decguard diff`. `diff`
  covers:
  - answer flips, confidence and distribution shifts;
  - accuracy, calibration and latency deltas;
  - new and recovered errors, per-segment changes;
  - contract `regression` gates, with an implicit `max_error_rate_increase: 0`.
- Mock backend: `position_bias`, a deliberate order-sensitivity defect for demos. The
  mock also understands reordered and reformatted options.

### Changed

- Replay treats transformed-case backend errors as Step-2 failures and reproduces them
  only when the backend returns the same stable error kind.
- Mock rules match ignoring whitespace differences as well as case.
- Examples declare properties; `severity` uses object inputs (`text`, `affected_users`).
  The refund example's `max_ece` is 0.2.
