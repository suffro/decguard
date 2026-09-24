# Reports, metrics and gates

`decguard test` produces one report. `--output report.json` writes it as JSON,
`--format json` prints it to stdout; the default terminal view is a summary of the same
data.

## JSON report (`report_version` 0.1)

| field | content |
| --- | --- |
| `report_version`, `decguard_version`, `created_at` | format and tool provenance |
| `status`, `exit_code` | `pass` / `warn` / `fail`, and 0 / 0 / 1 |
| `contract` | name, type, labels, schema version, `sha256:` hash, path |
| `dataset` | path, `sha256:` hash of the file bytes, case and labeled counts |
| `backend`, `health` | backend name, provider, model, version, redacted details; healthcheck result |
| `evaluation` | the evaluation settings used |
| `metrics` | `counts`, `classification`, `calibration`, `selective`, `latency` |
| `checks` | one entry per gate: level, metric, comparison, threshold, value, status |
| `failures` | failing examples (errors and wrong answers) with their inputs |
| `results` | every case: input, expected, metadata, and a `result` or an `error` |

Because `results` holds every normalized decision, `decguard report <file> --contract
<contract>` can recompute metrics and re-apply gates offline; recomputation from the same
results is bit-identical.

## Metrics

Classification and calibration metrics use **labeled** cases the backend decided. Coverage
and latency use all decided cases. Errors are counted separately and never dropped.

- **accuracy**: share of labeled cases where the selected label is the expected one.
- **macro_f1**: unweighted mean F1 over labels that appear as expected or predicted
  (scikit-learn's `average="macro"`; undefined precision/recall count as 0).
  `per_label` has precision, recall, F1 and support for each label.
- **ordinal_mae** (score only): mean |predicted level − expected level| in scale steps.
- **nll**: mean −ln p(expected). p is floored at 1e-15, so a confident miss adds about 34.5
  instead of infinity.
- **brier**: multi-class Brier score, mean of Σₖ (pₖ − yₖ)², range 0–2. (For two labels this
  is twice the binary `(p − y)²` form.)
- **ece**: expected calibration error over top-label confidence with `calibration_bins`
  equal-width bins; bin *i* covers (i/n, (i+1)/n], the first also includes 0. `reliability`
  lists count, mean confidence and accuracy per bin.
- **coverage / abstention_rate**: share of decisions with confidence ≥ / <
  `evaluation.confidence_threshold`. **selective_accuracy**: accuracy on labeled cases at or
  above it.
- **error_rate**: errored cases / all cases, with `errors_by_kind`.
- **latency**: mean, p50/p90/p95/p99 (linear interpolation, NumPy's default) and max of the
  time spent in the backend call, in milliseconds.

Calibration is reported separately from accuracy on purpose: a model can be accurate and
badly calibrated, which matters as soon as its confidence drives an action.

## Status and exit codes

- **FAIL** (exit 1): at least one requirement does not hold, including the implicit
  `max_error_rate: 0`, or a gated metric could not be computed.
- **WARN** (exit 0, or 1 with `--fail-on-warn`): requirements hold, a warning gate does not.
- **PASS** (exit 0): everything holds.
- Exit **2**: the run could not be evaluated: invalid contract or dataset, unknown backend,
  missing credentials, unhealthy backend, every case failing, invalid CLI usage, or an
  internal error.
