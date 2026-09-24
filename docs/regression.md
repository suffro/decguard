# Regression diffs

`decguard diff` compares two stored reports of the same decision, typically the current
model (baseline) and a new model or version (candidate), and fails CI when the candidate
regresses beyond the contract's limits.

```bash
decguard test decguard.yaml -o baseline.json
decguard test decguard.yaml --backend candidate -o candidate.json
decguard diff baseline.json candidate.json --contract decguard.yaml
```

Cases are matched by id. Only matched cases are compared, and both runs' metrics are
recomputed on them with the same `evaluation` settings, so the numbers stay comparable
even if the datasets differ slightly. Unmatched cases are counted.

## What is compared

- **Answers**: flips (selected label changed), newly wrong and newly correct labeled cases.
- **Distributions**: mean and max total variation distance, mean Jensen-Shannon
  divergence.
- **Confidence**: mean signed shift, mean and max absolute shift.
- **Metrics**: accuracy, macro-F1, ordinal MAE, ECE, Brier, NLL, coverage, error rate,
  latency p50/p95 (baseline, candidate, delta).
- **Failures**: cases that newly error, recover, or still error.
- **Segments**: per value of each `segment_by` metadata key (or `--segment-by KEY`), the
  accuracy before and after and the flip rate.

Every changed case is listed with its input, so a regression can be inspected directly.

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

The top-level gates are requirements (exit 1); `warnings` takes the same gates (WARN).

| gate | value |
| --- | --- |
| `max_answer_flip_rate` | flips / cases both runs decided |
| `max_accuracy_drop`, `max_macro_f1_drop` | baseline − candidate |
| `max_ece_increase`, `max_brier_increase`, `max_nll_increase` | candidate − baseline |
| `max_mean_tv_distance` | mean total variation distance |
| `max_mean_confidence_shift` | mean absolute confidence shift |
| `max_error_rate_increase` | candidate − baseline error rate; **defaults to 0** |
| `max_latency_p95_increase_ms` | candidate − baseline p95 latency |
| `max_segment_accuracy_drop` | worst accuracy drop over segments with ≥ `min_segment_size` cases (needs `segment_by`) |

Without `--contract`, only the implicit `max_error_rate_increase: 0` applies. A gate
whose value cannot be computed (e.g. accuracy without labels) fails.

Output: a terminal summary, `--format json`, and `--output diff.json`. The JSON diff
(`diff_version` 0.1) records both runs' provenance (backend, model/version, contract and
dataset hashes).
