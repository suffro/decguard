---
description: Metamorphic properties - option order, label format, irrelevant and repeated context, whitespace, paraphrase, noul inversion and score monotonicity - with their limits and defaults.
---

# Metamorphic properties

Golden tests check answers to fixed inputs. A **metamorphic property** checks how the
answer behaves when the input changes in a controlled way, so it needs no extra labels and
catches failures a golden set cannot see.

Most properties are **invariances**: listing the options in a different order, formatting
the labels differently, adding an irrelevant sentence or extra whitespace must not change
the decision. Two are not: [`inversion`](#inversion-noul) expects a yes/no answer to
**swap**, and [`monotonic`](#monotonic-score) expects a score to **move in one direction**.

Properties run with `decguard fuzz` (properties only) or `decguard test --all` (golden
gates and properties in one report). How runs are seeded, minimized and replayed is
described in [Fuzzing and replay](./fuzzing.md).

## How a property is checked

1. Each dataset case is decided as is: the **original**.
2. The property derives one or more **transformed** cases from it, deterministically from
   the [seed](./fuzzing.md#seeds-and-reproducibility).
3. Each transformed case is sent to the same backend.
4. The two probability distributions are compared, and the comparison is checked against
   the property's limits.

Everything is recorded in the report: the transformation steps, what was sent, the result
(mapped back to contract labels), the comparison and any violation.

**Option presentation is separate from the input.** `option_order` and `label_format` do
not edit the input text; they change how the labels are presented to the model. Backends
receive the labels in the order and form shown (`request.decision.labels` in Python,
`decision.labels` over [HTTP](./http.md), the question's `criteria` for
[System One](./systemone.md)) and answer with probabilities keyed by those labels. DecGuard
maps them back to the contract labels before comparing.

## Configuring properties

```yaml
fuzz:
  seed: 42

properties:
  option_order:
    samples: 3
    max_tv_distance: 0.03  # per transformed case
    max_flip_rate: 0       # share of transformed cases whose answer changes
  irrelevant_context:
    insertions: 2
    max_tv_distance: 0.05
    level: warning         # requirement (default) fails the run; warning only warns
```

A property is enabled by being present; `enabled: false` turns it off while keeping its
settings. Every property except `monotonic` needs at least one limit. Contract validation
rejects a property that does not apply to the decision type, for example `monotonic` on a
`choice` decision.

### Settings shared by every property

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | turn the property off without deleting it |
| `level` | `requirement` | `requirement` fails the run on violation; `warning` turns PASS into WARN |
| `samples` | per property | transformed cases generated per dataset case |

### Limits

| Key | Scope | Meaning |
| --- | --- | --- |
| `max_tv_distance` | per transformed case | total variation distance, ½ Σ \|p − q\|, 0–1 |
| `max_js_divergence` | per transformed case | Jensen-Shannon divergence in bits, 0–1 (symmetric, finite) |
| `max_abs_delta` | per transformed case | largest change of any single label's probability |
| `max_confidence_delta` | per transformed case | change of the selected label's confidence |
| `max_violation_rate` | aggregate, default `0` | share of transformed cases allowed to break a per-case limit |
| `max_flip_rate` | aggregate | share of transformed cases whose selected label may change |

Every comparison also records the confidence delta, whether the answer flipped and
whether the ranking of the labels changed. A failing check shows how far the distribution
moved as well as whether the top answer flipped: a model can keep the same answer and
still shift 20% of its probability mass because of the option order.

### Checks produced

Each enabled property adds up to three checks to the report:

- `<name>.max_violation_rate` — when a per-case limit is set;
- `<name>.max_flip_rate` — when set;
- `<name>.max_error_rate` — always, as a requirement fixed at `0`. If the backend fails on
  a transformed case, or the original case failed, the property was not demonstrated.
  If no case could be transformed at all, the check fails too.

## Property catalog

| Property | Decisions | Transformation | Expected |
| --- | --- | --- | --- |
| [`option_order`](#option-order) | choice, noul | present the options in another order | invariant |
| [`label_format`](#label-format) | all | reformat the labels, or use aliases | invariant |
| [`irrelevant_context`](#irrelevant-context) | all | insert irrelevant sentences | invariant |
| [`repeated_context`](#repeated-context) | all | insert one irrelevant sentence several times | invariant |
| [`whitespace`](#whitespace) | all | change whitespace | invariant |
| [`paraphrase`](#paraphrase) | all | replace the text with a paraphrase | invariant |
| [`inversion`](#inversion-noul) | noul | negate the input with a literal rewrite | answer swaps |
| [`monotonic`](#monotonic-score) | score | increase or decrease a numeric input field | score does not move against the direction |

### `option_order`

Presents the options as distinct permutations of the contract order. Catches position
bias: models that favour whichever option is listed first.

| Key | Default |
| --- | --- |
| `samples` | `3` distinct permutations (1–100) |

### `label_format`

Changes the surface form of the labels.

| Key | Default | Meaning |
| --- | --- | --- |
| `styles` | all seven | any of `upper` (`REFUND`), `lower`, `capitalized` (`Refund`), `lettered` (`A) refund`), `numbered` (`1. refund`), `quoted` (`"refund"`), `bracketed` (`[refund]`) |
| `aliases` | `{}` | alternative wordings per label; variant *i* uses every label's *i*-th alias |
| `samples` | `2` | variants per case |

For `noul` decisions this covers affirmative/negative surface variation, such as `YES` /
`NO`, `"yes"`, or aliases like `true` / `false`:

```yaml
properties:
  label_format:
    styles: [upper, capitalized, quoted]
    aliases: {spam: [junk], ham: [legitimate]}
    max_tv_distance: 0.02
```

### `irrelevant_context`

Inserts sentences that should not affect the decision at sentence boundaries of the text.

| Key | Default | Meaning |
| --- | --- | --- |
| `fragments` | eight neutral English sentences | the sentences to insert |
| `insertions` | `1` (1–10) | sentences inserted per transformed case |
| `samples` | `2` | transformed cases per case |

The default fragments are generic ("The weather was mild that day."). Supply your own
that are truly irrelevant for **your** decision; a sentence about shipping is not
irrelevant to a refund decision.

### `repeated_context`

Inserts one fragment several times, to catch models distracted by repetition.

| Key | Default |
| --- | --- |
| `fragments` | the same defaults as `irrelevant_context` |
| `repeats` | `3` (2–20) |
| `samples` | `1` |

### `whitespace`

Applies whitespace edits: doubled spaces, line breaks, tabs, leading and trailing blanks.

| Key | Default |
| --- | --- |
| `edits` | `3` (1–20) edits per transformed case |
| `samples` | `2` |

### `paraphrase`

Replaces the text with paraphrases from a provider.

```yaml
properties:
  paraphrase:
    source: {provider: identity}   # the default
    max_tv_distance: 0.0
```

| Key | Default |
| --- | --- |
| `source` | `{provider: identity}` |
| `samples` | `1` (1–20) paraphrases per case |

Providers:

- **`identity`** — re-asks the same input. No model needed; it catches backends that
  answer differently each time (non-determinism).
- **`file`** — curated paraphrases, deterministic and reviewable:
  `source: {provider: file, path: paraphrases.jsonl}`, relative to the contract, with rows
  `{"id": "<case id>", "paraphrases": ["...", "..."]}` or
  `{"input": "<text>", "paraphrases": [...]}`.
- **`openai`** — any OpenAI-compatible chat-completions API:

  ```yaml
  source:
    provider: openai
    model: gpt-4o-mini
    url: https://api.openai.com/v1   # default
    api_key_env: OPENAI_API_KEY      # default; null for local servers without a key
    timeout_s: 60                    # default
    temperature: 0.0                 # default
  ```

  The run seed is sent with the request, and the model and system fingerprint are recorded.
  LLM output is not guaranteed to be reproducible, so [replay](./fuzzing.md#replay) uses
  the stored paraphrase text.
- **Plugins** — a `decguard.fuzz.paraphrase.Paraphraser` subclass registered under the
  `decguard.paraphrasers` entry-point group.

A provider failure is recorded as a `paraphrase_error` for the case.

### `inversion` (noul)

Applies the first matching literal rewrite (`find` → `replace`, first occurrence) that
negates the input. The answer must **swap**: the comparison is made with the labels
swapped, so `max_tv_distance` measures the distance from the perfectly inverted answer.

```yaml
properties:
  inversion:
    rewrites:
      - {find: " is eligible", replace: " is not eligible"}
    max_tv_distance: 0.1
    max_flip_rate: 0      # the answer must invert
```

| Key | Default | Meaning |
| --- | --- | --- |
| `rewrites` | required, at least one | tried in order |
| `samples` | `1` (1–20) | applicable rewrites used per case |

Only use rewrites whose meaning you know inverts the decision. This is a separate property
from the invariances, so a model that ignores negation fails here while it may pass
everything else.

### `monotonic` (score)

Adds each of `deltas` to a numeric field of object inputs. The score must not move against
`direction`.

```yaml
fuzz:
  text_field: text          # other properties edit input.text

properties:
  monotonic:
    field: affected_users
    direction: increasing   # more affected users must not lower the severity
    deltas: [100, 10000]
    max_level_decrease: 0.05
    max_flip_rate: 0        # the selected level must not move against the direction
```

| Key | Default | Meaning |
| --- | --- | --- |
| `field` | required | top-level numeric key of object inputs |
| `direction` | `increasing` | `increasing`: a larger value must not lower the score; `decreasing`: the opposite |
| `deltas` | `[1.0]` | positive amounts added to the field, one transformed case each |
| `max_level_decrease` | `0.0` | allowed move of the expected level against the direction, in scale steps |

The **expected level** is Σ index × probability over the ordered levels, so this compares
the whole distribution, not only the top answer.

## Inputs a property cannot transform

Text transformations need string inputs, or [`fuzz.text_field`](./contracts.md#fuzz) to
name the key to edit in object inputs. A case a property cannot transform — no text, no
matching rewrite, a missing numeric field — is listed under `properties.skipped` in the
report with the reason. It is never dropped silently.
