# Built-in `systemone` backend and real-backend validation

## Context

v0.1 could not be tagged until DecGuard made genuine decisions through the real backends it
targets: Kev (open weights, self-hosted `POST /v1/systemone`) and Jev (TypeSafe; reached
through OpenRouter). Both speak TypeSafe's System One wire format: a `state`, a map of typed
`questions` (`choice` / `noul` / `score` with `instructions` and `criteria`), and typed
`answers`. That is not `decguard.http/0.1`. Step 1 deferred any real adapter
(`backend-plugins-via-entry-points.md`) because those APIs were not available to design
against. They now are, and are documented: docs.typesafe.ai/api, OpenRouter's Decisions API
reference (`POST https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`) and
github.com/jaredpalmer/kev.

## Decision

- Ship `systemone` as a built-in provider. It is a subclass of the `http` backend, so it
  reuses the httpx client, URL/credential checks, timeouts, retries, environment-only
  credentials and the rule that error bodies are never recorded. It adds 429/529 as
  retryable statuses, as TypeSafe and OpenRouter document. It adds no dependency and no
  vendor SDK.
- One DecGuard decision is sent as one question, keyed by the decision name. `instructions`
  come from the backend's `instructions` setting or `decision.description`, and one of
  them is required.
- Translation: choice labels are sent as `criteria` keys with `null` descriptions, and the
  answer's `probabilities` are read by option. Noul sends no labels, and `noul` is the
  probability of the first (positive) contract label. Score levels are sent as the ordered
  `criteria` list, and the answer's `probabilities` are read by level index. Labels are
  sent as shown, so fuzzing works as with `http`. For noul, reordered labels are mapped by
  name and reformatted labels by position (label_format keeps the contract order).
- Answers are validated, never repaired: exactly one answer of the right type, `model`
  present, a choice must be the most probable option, and a score legend must echo the
  levels sent. The provider's `confidence` is ignored because it is a different quantity.
- Provenance: per result, `model_version` is the model that answered (for Jev the dated
  snapshot). `metadata` holds `request_id`, `upstream_provider` and `usage`
  (`input_tokens`, `output_tokens`, `cost`). The backend metadata lists `served_models` and
  `upstream_providers`.
- Jev rounds probabilities to two decimals. Contracts must widen
  `evaluation.probability_tolerance` (the real contracts use 0.02) instead of DecGuard
  rescaling anything.
- Real validation (`tests/integration/test_real_backends.py`, contracts in
  `tests/integration/real/`) uses the markers `real_kev` and `real_jev`. The tests are
  skipped unless selected with `-m`. Once selected, missing prerequisites fail them. Kev
  runs upstream `kev.serve` at a pinned commit, serving Kev-0.8B at a pinned Hub revision.
  Jev runs `typesafe/jev-1.13` on OpenRouter with `OPENROUTER_API_KEY`. The
  `Real backends` workflow runs them on Ubuntu and macOS (Python 3.13), started by
  `workflow_dispatch` or the `real-backends` pull-request label.

## Alternatives considered

- A separate plugin package or proxy: keeps the core smaller, but the wire format is the
  public contract of the target ecosystem and the adapter is about 200 lines of code with no
  dependency. Rejected.
- The TypeSafe Python SDK: an extra runtime dependency for a single POST. Rejected.
- OpenRouter's `/api/v1/systemone` instead of the Decisions API: the same body. The
  Decisions API is OpenRouter's documented primary surface for Jev, and the backend works
  with either URL.
- Several questions per request, for cost: DecGuard decides one decision per case, and
  batching would couple cases. Not needed at v0.1 scale.

## Consequences

- Kev on GitHub-hosted runners installs its locked dependencies (CUDA torch wheels on Linux)
  and downloads about 1.8 GB of weights, which are cached by pinned revision. That is why
  the workflow is manual.
- Changing the pinned Kev commit, checkpoint or Jev model means updating the workflow env,
  `docs/systemone.md` and the real contracts together.
