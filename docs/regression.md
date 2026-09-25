---
description: Compare a baseline and a candidate model run case by case, and fail CI on answer flips, calibration loss, distribution shifts, new errors or segment regressions.
---

# Regression diffs

`decguard diff` compares two stored reports of the same decision — typically the model in
production (**baseline**) and a new model, version or backend (**candidate**) — and fails
when the candidate regresses beyond the contract's `regression` limits.

```bash
decguard test decguard.yaml -o baseline.json
decguard test decguard.yaml --backend candidate -o candidate.json
decguard diff baseline.json candidate.json --contract decguard.yaml
```

Aggregate gates can hide a regression: two models with the same accuracy can disagree on
many cases, or one can be much less calibrated. A diff compares the runs **case by case**.

## How runs are compared

- Cases are **matched by id**. Only matched cases are compared; cases present in only one
  report are counted.
- Both runs' metrics are **recomputed on the matched cases** with the same `evaluation`
  settings (the contract's with `--contract`, otherwise the candidate report's), so the numbers stay comparable even if the
  datasets differ slightly.
- Both reports must be for the same decision (name, type and labels).
- The diff records both runs' provenance: backend, model and version, contract and dataset
  hashes, and whether the dataset was the same.

## Example

The refund example's `order_sensitive` backend keeps every answer but shifts probability
mass toward the first option. Compared with the stable model:

```bash
decguard test examples/refund/decguard.yaml -o stable.json
decguard test examples/refund/decguard.yaml -b order_sensitive -o candidate.json
decguard diff stable.json candidate.json -c examples/refund/decguard.yaml
```

```text
DecGuard 0.1.1 · diff refund_request (choice) · FAIL

  baseline  stable.json  default: mock · refund-mock-v1
  candidate candidate.json  order_sensitive: mock · refund-mock-v2

  Cases        11 matched · 11 compared · 0 only in baseline · 0 only in candidate
  Answers      0 flipped (0.0%) · 0 newly wrong · 0 newly correct
  Errors       0 new · 0 recovered · 0 still
  Shift        mean TV 0.051   max TV 0.097   mean JS 0.008
  Confidence   mean shift -0.039   mean |shift| 0.045   max |shift| 0.093

  Metric            baseline  candidate     delta
  accuracy             1.000      1.000    +0.000
  macro_f1             1.000      1.000    +0.000
  ece                  0.139      0.175    +0.036
  brier                0.049      0.078    +0.030
  nll                  0.159      0.208    +0.049
  coverage             0.727      0.545    -0.182
  error_rate           0.000      0.000    +0.000
  latency_p50_ms       0.005      0.005    +0.000
  latency_p95_ms       0.012      0.009    -0.003

  Segments
    locale=en             n=11   accuracy 1.000 -> 1.000   flips 0.0%

  Checks
    PASS  max_answer_flip_rate           answer_flip_rate 0 <= 0.05
    PASS  max_accuracy_drop              accuracy_drop -0 <= 0.02
    PASS  max_ece_increase               ece_increase 0.0361 <= 0.05
    FAIL  max_mean_tv_distance           mean_tv_distance 0.05082 violates <= 0.03
    PASS  max_error_rate_increase        error_rate_increase 0 <= 0

FAIL: the candidate regresses beyond the contract's limits
```

Accuracy and answers are unchanged, but the candidate is less confident (coverage at the
0.8 threshold drops from 0.727 to 0.545), less calibrated, and its distributions moved by
a mean total variation distance of 0.051, beyond the allowed 0.03. The diff exits `1`.

## What is compared

- **Answers** — flips (selected label changed), newly wrong and newly correct labeled cases.
- **Distributions** — mean and max total variation distance, mean Jensen-Shannon
  divergence.
- **Confidence** — mean signed shift, mean and max absolute shift.
- **Metrics** — accuracy, macro-F1, ordinal MAE, ECE, Brier, NLL, coverage, error rate,
  latency p50/p95: baseline, candidate and delta.
- **Errors** — cases that newly error, recover, or still error.
- **Segments** — per value of each `segment_by` metadata key (or `--segment-by KEY`):
  accuracy before and after, and flip rate.

Every flipped, newly errored or recovered case is listed under `changes` with its input,
both answers and confidences, so a regression can be inspected directly.

## Gates

```yaml
regression:
  max_answer_flip_rate: 0.005
  max_accuracy_drop: 0.01
  max_ece_increase: 0.02
  segment_by: [locale]
  min_segment_size: 5
  max_segment_accuracy_drop: 0.05
  warnings:
    max_mean_confidence_shift: 0.03
```

Gates at the top level of `regression` are requirements (exit `1`); `regression.warnings`
takes the same gates at warning level.

| Gate | Value checked (must be ≤ the limit) |
| --- | --- |
| `max_answer_flip_rate` | flips / cases both runs decided |
| `max_accuracy_drop` | baseline − candidate accuracy |
| `max_macro_f1_drop` | baseline − candidate macro-F1 |
| `max_ece_increase` | candidate − baseline ECE |
| `max_brier_increase` | candidate − baseline Brier score |
| `max_nll_increase` | candidate − baseline NLL |
| `max_mean_tv_distance` | mean total variation distance between matched distributions |
| `max_mean_confidence_shift` | mean absolute confidence shift |
| `max_error_rate_increase` | candidate − baseline error rate; **defaults to 0** |
| `max_latency_p95_increase_ms` | candidate − baseline p95 latency |
| `max_segment_accuracy_drop` | worst accuracy drop over segments with ≥ `min_segment_size` matched cases (needs `segment_by`) |

| Setting | Default | Meaning |
| --- | --- | --- |
| `segment_by` | `[]` | case `metadata` keys whose values define segments |
| `min_segment_size` | `5` | smallest segment that `max_segment_accuracy_drop` considers |

Without `--contract`, only the implicit `max_error_rate_increase: 0` applies. A gate whose
value cannot be computed (for example accuracy without labeled cases) fails.

## Output

A terminal summary by default; `--format json` prints the diff report to stdout and
`--output diff.json` writes it (`diff_version` 0.1, see [Reports](./reports.md#diff-report)).
`--fail-on-warn` makes warning-level regressions exit `1`.

## Typical uses

- **Model upgrade in CI.** Test the production backend and the candidate on the same
  golden dataset in one job, diff them, and block the merge on regressions. See
  [CI](./ci.md#regression-gate-for-a-model-upgrade).
- **Backend migration.** Moving from a self-hosted Kev server to Jev through OpenRouter, or
  the other way round, is a diff between two backends of the same contract.
- **Stored baseline.** Keep the production model's report as a build artifact and diff each
  candidate against it, without re-running the baseline.
