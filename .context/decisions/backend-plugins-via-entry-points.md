# Backend plugins via entry points

## Context

DecGuard must support remote endpoints, local/custom Python decision providers and future
model families (Open-Jev, Kev, …) without hard-coding one of them. Contracts and datasets
are untrusted input, and the plan forbids executing arbitrary code from contracts.

## Decision

- A contract's `backend.provider` names either a built-in (`mock`, `http`) or an installed
  plugin registered under the `decguard.backends` entry-point group. Contracts never
  contain import paths. Built-in names cannot be shadowed by plugins.
- Adapters subclass `DecisionBackend` and implement only `predict()` (raw label
  probabilities) plus `from_config()` (settings validation, no I/O). The shared `decide()`
  measures latency and validates/normalizes, so every backend yields identical
  `DecisionResult` semantics.
- Python code can also be used directly through `CallableBackend` in the Python API.
- The generic HTTP backend speaks a small documented JSON protocol, `decguard.http/0.1`
  (docs/http.md), with `label_map` for differing label names. Credentials come only
  from environment variables.
- No real Open-Jev/Kev adapter ships in Step 1: their APIs were not available to design
  against, and CI must not need model downloads or GPUs. The opt-in external test
  (`pytest -m external`, `DECGUARD_EXTERNAL_CONTRACT`) runs any real endpoint.

## Alternatives considered

- `module:function` references in contracts: simplest for users, but lets a contract run
  arbitrary code. Rejected.
- Provider-specific fields as a pydantic discriminated union in the contract schema:
  strict, but closes the schema to plugins. Instead provider settings are extra keys on
  `backend`, validated by the provider's own settings model and reported against the
  contract path (`backend.<field>`).

## Consequences

- Third-party backends are separate packages; `decguard validate` validates their
  settings offline.
- Backends run concurrently in threads (`evaluation.max_concurrency`) and must be
  thread-safe.
