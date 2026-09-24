# Metamorphic properties and fuzzing

A property says how a decision must behave when the input changes in a controlled way. Most
properties are **invariances**: an irrelevant sentence, a different option order or extra
whitespace must not change the answer. Two are not: `inversion` expects the answer to
**swap**, and `monotonic` expects a score to **move in one direction**.

```bash
decguard fuzz decguard.yaml                 # properties only
decguard test decguard.yaml --all           # golden gates + properties
decguard fuzz decguard.yaml -p option_order --seed 7 --output fuzz.json
```

Each dataset case is first decided as is (the *original*). Every property then derives
transformed cases from it, sends them to the same backend and compares the two
probability distributions. Everything is recorded in the report: the transformation steps,
what was sent, the result (mapped back to contract labels), the comparison and the
violations.

## Contract sections

```yaml
fuzz:
  seed: 0                 # every transformation derives from (seed, property, case id)
  text_field: text        # object inputs: the key text transformations edit
  minimize: true          # shrink failing transformations
  max_minimize_calls: 32  # backend calls per failing case while shrinking

properties:
  option_order:
    samples: 3
    max_tv_distance: 0.03 # per transformed case
    max_flip_rate: 0      # share of transformed cases whose answer changes
  irrelevant_context:
    insertions: 2
    max_tv_distance: 0.05
    level: warning        # requirement (default) fails the run; warning only warns
```

A property is enabled by being present (`enabled: false` turns it off). It needs at least
one limit.

### Limits (all properties except `monotonic`)

| key | per transformed case | meaning |
| --- | --- | --- |
| `max_tv_distance` | yes | total variation distance: ½ Σ \|p − q\|, 0–1 |
| `max_js_divergence` | yes | Jensen-Shannon divergence in bits, 0–1 (symmetric, finite) |
| `max_abs_delta` | yes | largest change of any one label's probability |
| `max_confidence_delta` | yes | change of the selected label's confidence |
| `max_violation_rate` | aggregate, default `0` | share of transformed cases allowed to break a per-case limit |
| `max_flip_rate` | aggregate | share of transformed cases whose selected label may change |

Every comparison also records the confidence delta, whether the answer flipped and
whether the ranking of the labels changed. A failing check therefore shows how far the
distribution moved as well as whether the top answer flipped.

Checks per property: `<name>.max_violation_rate` (when a per-case limit is set),
`<name>.max_flip_rate` (when set) and `<name>.max_error_rate`. The error check is always a
requirement fixed at 0: if the backend fails on a transformed case, or the original case
failed, the property was not demonstrated. If no case could be transformed, the check
fails too.

## Properties

| property | decisions | transformation | expected |
| --- | --- | --- | --- |
| `option_order` | choice, noul | present the options in another order (`samples` distinct permutations) | invariant |
| `label_format` | all | reformat the labels: `styles` from `upper`, `lower`, `capitalized`, `lettered` (`A) refund`), `numbered` (`1. refund`), `quoted`, `bracketed`; plus `aliases` | invariant |
| `irrelevant_context` | all | insert `insertions` sentences from `fragments` at sentence boundaries | invariant |
| `repeated_context` | all | insert one fragment `repeats` times | invariant |
| `whitespace` | all | `edits` whitespace changes (double spaces, line breaks, tabs, leading/trailing) | invariant |
| `paraphrase` | all | replace the text with paraphrases from `source` | invariant |
| `inversion` | noul | apply the first matching `rewrites` (`find` → `replace`, first occurrence) | answer swaps |
| `monotonic` | score | add each of `deltas` to the numeric input `field` | score does not move against `direction` |

Option presentation is separate from the input. Backends receive the options in the
order and form shown (`request.decision.labels`, or `decision.labels` over HTTP), answer
with probabilities keyed by those labels, and DecGuard maps them back to the contract
labels before comparing. For `noul`, `label_format` covers affirmative/negative surface
variation (`YES`/`NO`, `"yes"`, or aliases such as `true`/`false`).

`fragments` defaults to neutral English sentences. Supply your own that are truly
irrelevant for your decision. Text transformations need string inputs, or
`fuzz.text_field` for object inputs. A case that a property cannot transform (no text,
no matching rewrite, missing numeric field) is listed under `properties.skipped` with the
reason; it is never dropped silently.

### `inversion` (noul)

```yaml
properties:
  inversion:
    rewrites:
      - {find: " is eligible", replace: " is not eligible"}
    max_tv_distance: 0.1  # distance between before and after with the labels swapped
    max_flip_rate: 0      # the answer must invert
```

Only use rewrites whose meaning you know inverts the decision. This is a separate
property from the invariances, so a model that ignores negation fails here while it may
pass everything else.

### `monotonic` (score)

```yaml
properties:
  monotonic:
    field: affected_users
    direction: increasing # more users must not lower the severity
    deltas: [100, 10000]
    max_level_decrease: 0.05  # allowed move of the expected level, in scale steps
    max_flip_rate: 0          # selected level must not move against the direction
```

The expected level is Σ index × probability over the ordered levels.

### `paraphrase` providers

```yaml
properties:
  paraphrase:
    source: {provider: identity}   # default: the same text again (checks determinism)
    max_tv_distance: 0.0
```

- `identity`: no model needed. It re-asks the same input, so it catches backends that
  answer differently each time.
- `file`: curated paraphrases, deterministic and reviewable: `source: {provider: file, path:
  paraphrases.jsonl}` with rows `{"id": "<case id>", "paraphrases": [...]}` or
  `{"input": "<text>", "paraphrases": [...]}`.
- `openai`: any OpenAI-compatible chat-completions API:
  - `source: {provider: openai, model: gpt-4o-mini, url: https://api.openai.com/v1, api_key_env: OPENAI_API_KEY}`;
  - temperature 0 and the run seed are sent;
  - the model and system fingerprint are recorded;
  - `api_key_env: null` for local servers.

  LLM output is not guaranteed to be reproducible, so replay uses the stored text.
- Plugins: a `decguard.fuzz.paraphrase.Paraphraser` subclass under the
  `decguard.paraphrasers` entry-point group.

Paraphrase failures are recorded as `paraphrase_error` for the case.

## Minimization

For `option_order`, `label_format`, `irrelevant_context`, `repeated_context` and
`whitespace`, a failing transformation is shrunk greedily until no smaller version still
fails, or until `max_minimize_calls` is spent:
- inserted fragments and whitespace edits are removed one at a time;
- reformatted labels are reverted one at a time;
- permutations are moved closer to the original order one adjacent swap at a time.

The smallest failing version is stored as `reduced` next to the full one.

## Reproducibility and replay

Transformations draw from a SHA-256-based stream keyed by `(seed, property, case id)`.
The same seed gives the same transformations on every platform and Python version, and
adding cases or properties does not change the others. Reports record:
- the seed and the fuzz settings;
- the property settings;
- the contract hash, dataset hash and backend metadata;
- every transformed case with its steps and any paraphrase provenance.

```bash
decguard replay fuzz.json                                   # every stored failure
decguard replay fuzz.json --id option_order/r1/0            # one of them
decguard replay fuzz.json --backend candidate               # against another backend
```

Replay does three things:
1. re-sends the original case and each stored failing transformation, including the
   reduced one, exactly as stored;
2. judges them again;
3. regenerates the transformation from the seed to confirm it matches the stored one.

It exits 1 if a failure still reproduces and 0 if none does. `decguard report fuzz.json
--contract edited.yaml` re-applies edited limits and levels to the stored cases without
calling the backend.
