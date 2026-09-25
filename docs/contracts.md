---
description: Complete reference for the Decision Contract, schema 0.1 - every section and field, defaults, validation rules and invalid combinations.
---

# Decision Contract reference

This page describes **schema `0.1`**, the contract format read by DecGuard `0.1.x`. For an
introduction, see [Decisions and results](./decisions.md) and the
[quickstart](./quickstart.md).

## File format

A contract is a YAML (`.yaml`, `.yml`) or JSON (`.json`) file, UTF-8, at most 1 MB.

Validation is strict. **Unknown keys, duplicate keys and wrong types are errors** that
name the offending field, so typos cannot silently disable a gate:

```text
error: decguard.yaml: invalid contract:
  requirements.min_acuracy: unknown field (check the spelling)
```

YAML is parsed with a safe loader; contracts never execute code or reference import paths.
Run [`decguard validate`](./cli.md#decguard-validate) to check a contract without calling
any backend.

```yaml
schema_version: "0.1"      # required
decision: {...}            # required
backend: {...}             # required: the default backend
backends: {name: {...}}    # named alternative backends
dataset: cases.jsonl       # golden dataset, relative to the contract
evaluation: {...}          # metric settings
requirements: {...}        # hard gates (golden tests)
warnings: {...}            # soft gates (golden tests)
properties: {...}          # metamorphic properties
fuzz: {...}                # fuzz settings
regression: {...}          # decguard diff gates
production: {...}          # decguard check gates and segments
policy: {...}              # runtime routes
```

**Names** — decision names, backend names and provider names — start with a letter or
digit and contain only letters, digits, `_`, `.` and `-`.

## `schema_version`

Required. The string `"0.1"`. Quote it in YAML: an unquoted `0.1` is a number and is
rejected.

## `decision`

Required. The question and its labels.

| Field | Types | Required | Meaning |
| --- | --- | --- | --- |
| `name` | all | yes | decision name; appears in reports, backend requests and production records |
| `type` | all | yes | `choice`, `noul` or `score` |
| `description` | all | no | the question in words; required by [`systemone`](./systemone.md) backends unless they set `instructions` |
| `options` | `choice` | yes | at least 2 unique labels |
| `labels` | `noul` | no | exactly 2 labels, positive first; default `[yes, no]` |
| `levels` | `score` | yes | at least 2 unique levels, lowest first; numbers become strings |

Labels must be non-empty, unique and have no surrounding spaces. Their order is the
canonical order: results list probabilities in this order, and ties for the highest
probability go to the label listed first.

## `backend` and `backends`

`backend` (required) is the default backend, named `default`. `backends` maps names to
alternative backends, selected with `--backend NAME` or named by
[policy](#policy) fallback routes. The name `default` is reserved.

| Field | Required | Meaning |
| --- | --- | --- |
| `provider` | yes | `mock`, `http`, `systemone`, or an installed plugin's name |
| `model` | no (yes for `systemone`) | model identifier passed to the backend |
| *other keys* | — | provider settings, validated by the provider; unknown keys are errors |

Provider settings:

- [`mock`](./backends.md#mock): `rules`, `default`, `seed`, `model_version`, `position_bias`;
- [`http`](./http.md#settings): `url`, `health_url`, `timeout_s`, `max_retries`,
  `retry_backoff_s`, `bearer_token_env`, `headers_from_env`, `headers`, `label_map`;
- [`systemone`](./systemone.md#settings): the `http` settings plus `instructions`;
- plugins: whatever their settings model defines ([Custom backends](./custom-backends.md)).

Contracts hold environment-variable **names**, never secret values. See
[Credentials](./backends.md#credentials).

## `dataset`

Optional. Path to the [golden dataset](./datasets.md) (`.jsonl` or `.json`), relative to
the contract file. `--dataset` overrides it on `validate`, `test` and `fuzz`. Commands
that need a dataset fail with exit code `2` when neither is given.

## `evaluation`

Optional. Settings shared by all metrics.

| Field | Default | Range | Meaning |
| --- | --- | --- | --- |
| `confidence_threshold` | none | 0–1 | decisions below it are abstentions; enables coverage metrics and gates |
| `calibration_bins` | `10` | 1–1000 | equal-width bins for ECE |
| `probability_tolerance` | `0.001` | > 0, ≤ 0.1 | how far a backend's probabilities may sum away from 1 |
| `max_concurrency` | `4` | 1–256 | parallel backend calls (`--max-concurrency` overrides) |

## `requirements` and `warnings`

Optional. Golden-test gates, applied by `test`, `test --all` and `report`. Both sections
accept the same keys. A violated requirement fails the run (exit `1`); a violated warning
turns PASS into WARN. See [Requirements and warnings](./gates.md).

| Gate | Range | Holds when |
| --- | --- | --- |
| `min_accuracy` | 0–1 | accuracy ≥ value |
| `min_macro_f1` | 0–1 | macro-F1 ≥ value |
| `max_nll` | ≥ 0 | negative log-likelihood ≤ value |
| `max_brier` | 0–2 | Brier score ≤ value |
| `max_ece` | 0–1 | expected calibration error ≤ value |
| `min_coverage` | 0–1 | share at/above `confidence_threshold` ≥ value |
| `max_abstention_rate` | 0–1 | share below `confidence_threshold` ≤ value |
| `min_selective_accuracy` | 0–1 | accuracy at/above `confidence_threshold` ≥ value |
| `max_error_rate` | 0–1 | errored cases / all cases ≤ value; **implicit requirement `0`** |
| `max_latency_p95_ms` | ≥ 0 | p95 backend latency ≤ value |
| `max_ordinal_mae` | ≥ 0 | mean level distance ≤ value (`score` only) |

Metric definitions: [Golden tests and metrics](./metrics.md).

## `properties`

Optional. Metamorphic properties, checked by `fuzz` and `test --all`. Each key enables
one property; see [Metamorphic properties](./properties.md) for behavior and examples.

Shared fields:

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | `false` disables the property but keeps its settings |
| `level` | `requirement` | `requirement` or `warning` |
| `max_tv_distance` | none | per-case limit, 0–1 (not `monotonic`) |
| `max_js_divergence` | none | per-case limit, 0–1 (not `monotonic`) |
| `max_abs_delta` | none | per-case limit, 0–1 (not `monotonic`) |
| `max_confidence_delta` | none | per-case limit, 0–1 (not `monotonic`) |
| `max_violation_rate` | `0` | share of transformed cases allowed to break a per-case limit |
| `max_flip_rate` | none | share of transformed cases whose selected label may change |

Every property except `monotonic` needs at least one of the four per-case limits or
`max_flip_rate`.

| Property | Decisions | Specific fields (defaults) |
| --- | --- | --- |
| `option_order` | choice, noul | `samples` (3) |
| `label_format` | all | `styles` (all of `upper`, `lower`, `capitalized`, `lettered`, `numbered`, `quoted`, `bracketed`), `aliases` ({}), `samples` (2) |
| `irrelevant_context` | all | `fragments` (8 neutral sentences), `insertions` (1), `samples` (2) |
| `repeated_context` | all | `fragments` (same defaults), `repeats` (3), `samples` (1) |
| `whitespace` | all | `edits` (3), `samples` (2) |
| `paraphrase` | all | `source` (`{provider: identity}`), `samples` (1) |
| `inversion` | noul | `rewrites` (required: list of `{find, replace}`), `samples` (1) |
| `monotonic` | score | `field` (required), `direction` (`increasing`), `deltas` ([1.0]), `max_level_decrease` (0.0) |

## `fuzz`

Optional. Settings for every property run.

| Field | Default | Meaning |
| --- | --- | --- |
| `seed` | `0` | every transformation derives from (seed, property, case id); `--seed` overrides |
| `text_field` | none | for object inputs: the top-level key whose string value text properties edit |
| `minimize` | `true` | shrink failing transformations; `--minimize/--no-minimize` overrides |
| `max_minimize_calls` | `32` | backend calls allowed per failing case while minimizing (0–1000) |

## `regression`

Optional. Gates applied by [`decguard diff --contract`](./regression.md). Gate keys at the
top level are requirements; the same keys under `regression.warnings` are warnings. Every
gate holds when the value is ≤ the limit.

| Field | Meaning |
| --- | --- |
| `max_answer_flip_rate` | share of cases whose selected label changed |
| `max_accuracy_drop`, `max_macro_f1_drop` | baseline − candidate |
| `max_ece_increase`, `max_brier_increase`, `max_nll_increase` | candidate − baseline |
| `max_mean_tv_distance` | mean total variation distance between matched distributions |
| `max_mean_confidence_shift` | mean absolute confidence shift |
| `max_error_rate_increase` | candidate − baseline error rate; **implicit requirement `0`** |
| `max_latency_p95_increase_ms` | candidate − baseline p95 latency |
| `max_segment_accuracy_drop` | worst accuracy drop over segments of at least `min_segment_size` cases |
| `warnings` | the same gates at warning level |
| `segment_by` | case metadata keys that define segments (default `[]`) |
| `min_segment_size` | smallest segment considered by `max_segment_accuracy_drop` (default `5`) |

## `production`

Optional. Gates and segments applied by [`decguard check`](./production.md).

| Field | Meaning |
| --- | --- |
| `segments` | metadata keys; one group per scalar value, plus `<missing>` |
| `requirements`, `warnings` | aggregate gates |
| `segment_requirements`, `segment_warnings` | gates applied to every segment group |

Aggregate gates: `min_accuracy`, `max_error_rate`, `max_ece`, `max_brier`, `max_nll`,
`min_threshold_coverage`, `max_abstention_rate`, `max_fallback_rate`, and the baseline
gates `max_confidence_tv_distance`, `max_accuracy_drop`, `max_ece_increase` (need
`--baseline`). Segment gates: the same without the three baseline gates. See the
[gate table](./production.md#metrics-drift-and-gates).

## `policy`

Optional. An ordered, first-match route table used by `decguard run` and the
[Python SDK](./policy.md#python-sdk).

| Field | Meaning |
| --- | --- |
| `routes` | at least one route |
| `routes[].when.confidence_gte` | condition: confidence ≥ this value (0–1); omit on the final route |
| `routes[].action` | `accept`, `abstain`, `fallback` or `human_review` |
| `routes[].backend` | for `fallback` only (required there): a backend declared in this contract |

## Invalid combinations

Besides type and range errors, the contract is rejected when:

| Rule | Error example |
| --- | --- |
| `min_coverage`, `max_abstention_rate` or `min_selective_accuracy` without `evaluation.confidence_threshold` | `requirements.min_coverage needs evaluation.confidence_threshold to be set` |
| `production` `min_threshold_coverage` without `evaluation.confidence_threshold` | `production min_threshold_coverage needs evaluation.confidence_threshold to be set` |
| `max_ordinal_mae` on a non-`score` decision | `requirements.max_ordinal_mae only applies to score decisions` |
| a property that does not apply to the decision type | `properties.option_order applies to choice and noul decisions, not score` |
| a property (except `monotonic`) with no limit | `set at least one of max_tv_distance, ... or max_flip_rate` |
| `label_format.aliases` for labels the decision does not have | `properties.label_format.aliases: unknown labels [...]` |
| `regression.max_segment_accuracy_drop` without `segment_by` | `max_segment_accuracy_drop needs segment_by (case metadata keys)` |
| a backend named `default` under `backends` | `'default' is reserved for the top-level 'backend'` |
| policy: the last route has a `when`, or an earlier route has none | `the final route must be unconditional` |
| policy: `confidence_gte` thresholds not strictly descending | `confidence_gte thresholds must be strictly descending` |
| policy: `fallback` without `backend`, or `backend` on another action | `fallback routes require 'backend'` |
| policy: `backend` not declared in the contract | `unknown backend 'x'; the contract defines: ...` |
| `systemone` without `model`, or without `decision.description` / `instructions` | `systemone backend 'default': 'model' is required` |
| `label_map` targets that are not contract labels, or two labels mapped to one | `label_map targets [...] are not contract labels` |
| `label_map` on a `systemone` `noul` decision | `label_map does not apply to noul decisions` |
| HTTP: literal credential headers, credentials in the URL, credential-like query parameters | `'Authorization' looks like a credential; ...` |
| HTTP: `bearer_token_env` and an `Authorization` header from the environment together | `set either bearer_token_env or an Authorization header, not both` |
| HTTP: `health_url` on another origin while credentials come from the environment | `health_url must use the backend URL's origin ...` |

Backend errors (the last six rows) are reported by `decguard validate`, which builds every
declared backend, and by any command that uses the backend.

## Contract hash

Reports record `sha256:` of the normalized contract: canonical JSON of the parsed model,
with defaults filled in. Reformatting, comments and key order do not change it; any
semantic change does. `decguard validate` prints it.

## Complete example

The repository's
[refund example](https://github.com/suffro/decguard/blob/main/examples/refund/decguard.yaml)
uses every section: a mock default backend, an order-sensitive candidate, a fallback
target and an HTTP staging backend; golden gates; six properties; regression limits;
production gates with segments; and a three-route policy. The
[severity](https://github.com/suffro/decguard/blob/main/examples/severity/decguard.yaml)
(`score`, object inputs, `monotonic`) and
[spam](https://github.com/suffro/decguard/blob/main/examples/spam/decguard.yaml) (`noul`,
`label_format`) examples cover the other decision types.
