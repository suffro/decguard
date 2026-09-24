# Metamorphic engine design

## Context

Step 2 of the v0.1 plan requires decision-specific metamorphic tests: controlled input
transformations whose effect on a probabilistic decision is compared distribution-aware.
Fuzzing must be deterministic under a seed, failures replayable and minimized where
reliable, and the paraphrase source must not require a paid LLM. Generic red-team tooling
(Promptfoo, garak) is out of scope.

## Decision

- **Transformations are pure step lists** (`fuzz/transforms.py`): `apply(original input,
  steps)` rebuilds the transformed case, so failures can be regenerated, replayed and shrunk.
- **Option presentation is separate from the input.** `DecisionRequest.decision.labels`
  carries the options as shown (reordered/reformatted). Backends answer in shown labels and
  the engine maps back to contract labels (`to_contract_labels`) before comparing. There is
  no change to the backend interface or the HTTP protocol.
- **Randomness comes from SHA-256** (`fuzz/rng.py`) keyed by `(seed, property, case id)`,
  not `random.Random`. Python only guarantees `random()` across versions, and per-case keys
  keep other cases stable when the dataset changes. Pinned by a test.
- **Relations are explicit**: `invariant`, `swapped` (noul inversion, compared with labels
  exchanged) and `monotonic` (score, expected-level direction), so invariance and inversion
  tests are never confused.
- **Limits apply per transformed case** (TV, JS, max abs delta, confidence delta) plus
  aggregate `max_violation_rate` (default 0) and `max_flip_rate`. Transformed-case errors
  are an implicit requirement fixed at 0; a property that evaluates nothing fails.
- **Reports** store every transformed case, the seed and the property settings. Loading a
  report re-checks each comparison and violation list against its results and settings,
  in the same spirit as Step 1's result invariants.
- **Minimization is greedy** and applies only where reduction is reliable: dropping steps
  for insertions, whitespace and label formats, and undoing adjacent inversions for
  permutations. It is bounded by `fuzz.max_minimize_calls`.
- **Paraphrase providers**: `identity` (default; checks determinism), `file` (curated), and
  `openai` (optional, OpenAI-compatible over the existing httpx dependency). Plugins use
  the `decguard.paraphrasers` entry-point group. Replay uses the stored paraphrase text.
- **`diff` compares reports on matched case ids** and recomputes both sides' metrics on
  that subset with one `evaluation`. `max_error_rate_increase` defaults to 0.

## Alternatives considered

- Seeded `random.Random`: simpler, but not reproducible across Python versions. Rejected.
- Encoding option order in the input text: backend-specific and not remappable. Rejected in
  favour of the shown-label protocol.
- A general delta debugger: overkill for v0.1 (plan: "do not overengineer").
- Promptfoo/garak adapters now: they target generic LLM red-teaming, not typed decision
  distributions. None added. Paraphrasers and backends are the integration points.

## Consequences

- No new runtime dependency.
- Backends must key probabilities by the labels as sent. The mock resolves formatted
  labels by meaning (case, enumerators, quotes) and matches rules ignoring whitespace.
- Changing transformation generation changes stored runs' regeneration check. Treat it
  like a format change: note it in the CHANGELOG.
