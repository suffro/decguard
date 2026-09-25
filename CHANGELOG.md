# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may break
compatibility; the contract (`schema_version`) and report (`report_version`) formats are
versioned separately.

## [Unreleased]

### Added

- Documentation site built with VitePress in `docs/` (`npm run dev` and
  `npm run build` in `docs/`): getting started, core concepts, testing, production, backends,
  CLI/contract/report reference, CI and architecture. New pages include a verified
  quickstart, a CLI reference and a complete contract reference; the backends guide is
  split into System One, HTTP and custom-backend pages. The README is now a short landing
  page that links into these docs.

## [0.1.1] - 2026-09-25

### Fixed

- The README, which is also the PyPI project page, installs with `pip install decguard` /
  `uv tool install decguard` instead of cloning the repository, and its links point to
  GitHub so they work on PyPI. The CI examples install from PyPI.

## [0.1.0] - 2026-09-24

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
  Stored reports are re-validated on load: results, dataset counts, metrics, failures,
  property summaries, checks, status and exit code must all agree; each case holds exactly
  one valid result or error.
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
- Backend-neutral production JSONL/JSON records and `decguard check`: offline accuracy,
  error/calibration, threshold coverage, routing, confidence, latency and cost summaries;
  drift against a prior dataset/report; metadata segments with independent gates; and a
  versioned, integrity-checked production report.
- Explicit deterministic `policy` routes for `accept`, `abstain`, named-backend `fallback`
  and `human_review`, exposed by `decguard run` and the embeddable `DecGuard` Python API.
  Fallback is a directive and is never invoked or optimized implicitly.
- `systemone` backend for System One decision APIs: self-hosted Kev servers, TypeSafe's
  Jev, and Jev through OpenRouter's Decisions API. It covers:
  - choice options sent as `criteria`, noul `noul` as the positive label's probability,
    score level indices mapped back to the ordered levels;
  - strict answer checks (question, type, most probable choice, score legend);
  - the served model, request id, upstream provider and usage/cost as provenance;
  - HTTP 429/529 retries, on top of the `http` backend's.
- Opt-in `real_kev` / `real_jev` tests with genuine inference (Kev-0.8B at a pinned
  revision; `typesafe/jev-1.13` on OpenRouter), and a manual `Real backends` workflow
  running them on Ubuntu and macOS. Selected tests fail, never skip, without their
  server, checkpoint or credential.
- Tag-triggered `Release` workflow: a `vX.Y.Z` tag that matches the package version is
  validated and built once. The same wheel and sdist are then published to PyPI through
  Trusted Publishing (with attestations) and attached to a generated GitHub Release.

### Changed

- Replay treats transformed-case backend errors as Step-2 failures and reproduces them
  only when the backend returns the same stable error kind.
- Mock rules match ignoring whitespace differences as well as case.
- Examples declare properties; `severity` uses object inputs (`text`, `affected_users`).
  The refund demo includes strict calibration/distribution-regression gates and a
  production-drift fixture.
- HTTP backend errors no longer include untrusted response bodies, preventing reflected
  secrets or private input from being persisted in reports. Credential-like URL query
  parameters are rejected, authenticated healthchecks stay on the backend origin, and
  common secret keys in result/backend metadata are redacted recursively.
