---
description: What decguard test does, and the exact definition of every golden-test metric - accuracy, calibration, confidence coverage, latency and errors.
---

# Golden tests and metrics

`decguard test` runs the [golden dataset](./datasets.md) through one backend, computes
reliability metrics, applies the contract's [requirements and warnings](./gates.md), and
produces one [report](./reports.md).

```bash
decguard test decguard.yaml                        # default backend
decguard test decguard.yaml --backend candidate    # a named backend
decguard test decguard.yaml --output report.json   # keep the full report
decguard test decguard.yaml --all                  # plus metamorphic properties
```

## What a run does

1. Loads and validates the contract and the dataset. Any problem stops the run with exit
   code `2`.
2. Calls the backend's healthcheck (skip it with `--no-healthcheck`). An `unhealthy`
   backend stops the run with exit code `2`; `unknown` (no health endpoint) continues.
3. Sends every case to the backend, up to `evaluation.max_concurrency` at a time (default
   4, `--max-concurrency` overrides). Results keep dataset order whatever the concurrency.
4. Validates each answer into a [`DecisionResult`](./decisions.md#the-normalized-decisionresult),
   or records a typed error for the case.
5. Computes the metrics below, evaluates the gates, and prints the report.

Metrics are deterministic: they are computed in dataset order with exact floating-point
summation, so the same results always give bit-identical numbers. That is what lets
[`decguard report --contract`](./cli.md#decguard-report) re-apply edited gates to a stored
report without calling the model.

## Which cases each metric uses

- **Classification and calibration** metrics use **labeled** cases the backend decided.
- **Coverage** and **latency** use all decided cases.
- **Errors** are counted over all cases and never dropped.

## Accuracy

- **`accuracy`** — share of labeled cases whose selected label is the expected one.
- **`macro_f1`** — unweighted mean F1 over the labels that appear as expected or
  predicted (scikit-learn's `average="macro"`; undefined precision or recall count as 0).
  The report's `per_label` has precision, recall, F1 and support for each label.
- **`ordinal_mae`** (score decisions only) — mean |predicted level − expected level| in
  scale steps. Predicting 3 when the answer is 4 costs 1; predicting 1 costs 3.

## Calibration

A model is **calibrated** when its confidence matches its accuracy: of all decisions made
at 80% confidence, about 80% are right. Calibration is reported separately from accuracy
on purpose. A model can be accurate and badly calibrated, and that matters as soon as its
confidence drives an action, such as a [policy](./policy.md) that automates only
high-confidence decisions.

- **`ece`** — expected calibration error over top-label confidence, with
  `evaluation.calibration_bins` equal-width bins (default 10). Bin *i* covers
  (i/n, (i+1)/n]; the first bin also includes 0. ECE is the case-weighted mean
  |accuracy − mean confidence| over bins. The report's `reliability` lists count, mean
  confidence and accuracy per bin, which is the data behind a reliability diagram.
- **`brier`** — multi-class Brier score: the mean of Σₖ (pₖ − yₖ)² over labels, from 0
  (perfect) to 2. For two labels this is twice the binary `(p − y)²` form.
- **`nll`** — mean negative log-likelihood, −ln p(expected). p is floored at 1e-15, so a
  confident miss adds about 34.5 instead of infinity.

ECE is easy to read; Brier and NLL also reward sharp, correct probabilities and punish
confident mistakes harder. Gate on ECE first, then add `max_brier` or `max_nll` when you
need them.

## Coverage and selective accuracy

Set `evaluation.confidence_threshold` to the confidence at which your application would
act on a decision automatically. Decisions below it are **abstentions**.

- **`coverage`** — share of decided cases with confidence ≥ the threshold.
- **`abstention_rate`** — share below it (1 − coverage).
- **`selective_accuracy`** — accuracy of labeled cases at or above the threshold: how good
  the decisions you would automate are.

The gates `min_coverage`, `max_abstention_rate` and `min_selective_accuracy` require the
threshold to be set; contract validation rejects them otherwise. For routing that acts on
these thresholds at runtime, see [Policies](./policy.md).

## Latency

Time spent in the backend call, in milliseconds: mean, p50, p90, p95, p99 (linear
interpolation, NumPy's default) and max. `max_latency_p95_ms` gates the 95th
percentile. Latency includes network time for remote backends and depends on
`max_concurrency`, so compare latency between runs made with the same settings.

## Errors

- **`error_rate`** — errored cases / all cases, with `errors_by_kind` (`timeout`,
  `unavailable`, `invalid_response`, `backend_error`, `exception`).

`max_error_rate` is an [implicit requirement of 0](./gates.md#implicit-gates). A backend
that fails on every case stops the run with exit code `2`.

## Gate reference

| Gate | Metric | Holds when |
| --- | --- | --- |
| `min_accuracy` | accuracy | value ≥ threshold |
| `min_macro_f1` | macro-F1 | ≥ |
| `max_ordinal_mae` | ordinal MAE (score decisions only) | ≤ |
| `max_ece` | expected calibration error | ≤ |
| `max_brier` | multi-class Brier score (0–2) | ≤ |
| `max_nll` | negative log-likelihood | ≤ |
| `min_coverage` | share of decisions at/above the threshold | ≥ |
| `max_abstention_rate` | share below the threshold | ≤ |
| `min_selective_accuracy` | accuracy at/above the threshold | ≥ |
| `max_error_rate` | share of cases the backend failed (defaults to 0) | ≤ |
| `max_latency_p95_ms` | 95th percentile latency | ≤ |

All gates are accepted under both `requirements` and `warnings`. See the
[contract reference](./contracts.md#requirements-and-warnings) for validation rules.

## Reading failures

When gates fail, the terminal report lists failing examples — wrong answers and errors —
with their inputs:

```text
  Failures (1 of 1)
    r7           expected review, got refund (0.96)
                 input: The lid was damaged, but I just want a replacement lid.
```

The JSON report keeps every case in `results`, including the full distribution, so you can
inspect confident mistakes, sort by confidence, or feed the report to
[`decguard diff`](./regression.md).
