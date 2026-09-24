# Decision Contract reference (schema 0.1)

A contract is a YAML (`.yaml`/`.yml`) or JSON (`.json`) file. Validation is strict:
unknown keys, duplicate keys and wrong types are errors that name the offending field.
Run `decguard validate <contract>` to check one without calling any backend.

```yaml
schema_version: "0.1"      # required, quoted string
decision: {...}            # required
backend: {...}             # required, the default backend
backends: {name: {...}}    # optional alternative backends
dataset: cases.jsonl       # optional, relative to the contract file
evaluation: {...}          # optional
requirements: {...}        # optional hard gates
warnings: {...}            # optional soft gates
properties: {...}          # optional metamorphic properties (decguard fuzz / test --all)
fuzz: {...}                # optional fuzz settings: seed, text_field, minimization
regression: {...}          # optional regression gates (decguard diff)
```

## `decision`

Common fields: `name` (letters, digits, `_`, `.`, `-`), `description` (optional), `type`.

| type | fields | labels |
| --- | --- | --- |
| `choice` | `options: [a, b, c]` (at least 2, unique) | unordered options |
| `noul` | `labels: [yes, no]` (optional, exactly 2) | boolean; positive label first |
| `score` | `levels: [1, 2, 3, 4]` (at least 2, unique) | ordered, lowest first; numbers become strings |

The label order in the contract is the canonical order: probabilities in results and
reports follow it, and when two labels tie for the highest probability the one listed
first is selected.

## `backend` and `backends`

```yaml
backend:
  provider: mock           # built-in: mock, http; or an installed plugin's name
  model: my-model          # optional, passed to the backend
  ...provider settings...

backends:
  candidate:
    provider: http
    url: https://...
```

`decguard test --backend candidate` runs the named backend; the top-level one is called
`default`. Provider settings are described in [backends.md](backends.md).

## `dataset`

Path to a golden dataset, relative to the contract. `decguard test --dataset` overrides it.

- `.jsonl`: one JSON object per line (blank lines ignored).
- `.json`: a list of objects.

Each case: `input` (string or JSON object, required), `expected` (a contract label,
optional), `id` (optional, defaults to `case-<n>`), `metadata` (optional object). Cases
without `expected` still count for coverage, latency and error rate. Invalid rows,
unknown labels and duplicate ids stop loading; nothing is skipped silently.

## `evaluation`

| key | default | meaning |
| --- | --- | --- |
| `confidence_threshold` | none | decisions with confidence below it are abstentions; enables coverage metrics |
| `calibration_bins` | 10 | equal-width bins for ECE |
| `probability_tolerance` | 0.001 | how far a backend's probabilities may sum away from 1 |
| `max_concurrency` | 4 | parallel backend calls (`--max-concurrency` overrides) |

## `requirements` and `warnings`

Both accept the same gates. A violated requirement fails the run (exit 1); a violated
warning turns PASS into WARN (exit 0 unless `--fail-on-warn`).

| gate | metric | holds when |
| --- | --- | --- |
| `min_accuracy` | accuracy | `>=` |
| `min_macro_f1` | macro-F1 | `>=` |
| `max_nll` | negative log-likelihood | `<=` |
| `max_brier` | multi-class Brier score (0–2) | `<=` |
| `max_ece` | expected calibration error | `<=` |
| `min_coverage` | share of decisions at/above the threshold | `>=` |
| `max_abstention_rate` | share below the threshold | `<=` |
| `min_selective_accuracy` | accuracy at/above the threshold | `>=` |
| `max_error_rate` | share of cases the backend failed | `<=` |
| `max_latency_p95_ms` | 95th percentile latency | `<=` |
| `max_ordinal_mae` | mean level distance (score only) | `<=` |

Coverage gates require `evaluation.confidence_threshold`. `max_error_rate` defaults to `0`
as a requirement: any case the backend could not decide fails the run unless you allow
some. A gate whose metric cannot be computed (for example accuracy with no labeled cases)
fails.

## Contract hash

Reports record `sha256:` of the normalized contract (canonical JSON of the parsed model),
so reformatting or reordering keys does not change it but any semantic change does.
Contracts contain environment-variable names, never secret values.

## `properties` and `fuzz`

Metamorphic properties (option order, label format, irrelevant context, whitespace,
paraphrase, noul inversion, score monotonicity) and their tolerances. See
[properties.md](properties.md).

## `regression`

Limits on how much a candidate run may degrade relative to a baseline, applied by
`decguard diff`. See [regression.md](regression.md).
