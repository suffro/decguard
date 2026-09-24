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
- CLI: `decguard validate`, `decguard test`, `decguard report` (with re-evaluation against
  an edited contract). Exit codes: 0 pass/warn, 1 gate failed, 2 configuration/runtime
  error.
