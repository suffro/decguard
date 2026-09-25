---
description: Analyze decisions your application already collected, offline - calibration and reliability after deployment, baseline drift, metadata segments and production gates.
---

# Production checks

A model that passed its golden tests can still drift after deployment: traffic changes,
a new locale arrives, an upstream model version changes silently. `decguard check`
analyzes decisions your application **already collected** and applies post-deployment
gates to them.

It is an offline batch command. It does not call a model, upload data, start a daemon,
ingest telemetry or require a DecGuard service. You export records; DecGuard reads a file.

```bash
decguard check decguard.yaml \
  --dataset production.jsonl \
  --baseline previous.jsonl \
  --output production-report.json
```

| Option | Meaning |
| --- | --- |
| `--dataset`, `-d FILE` | collected production records, `.jsonl` or `.json` (required) |
| `--baseline FILE` | a previous production dataset, or a JSON report from an earlier `decguard check` |
| `--output`, `-o FILE` | write the production report (`check_version` 0.1) |
| `--format json` | print the report as JSON |
| `--fail-on-warn` | exit `1` on warnings |

Exit codes are the usual `0` pass/warn, `1` failed gate, `2` invalid configuration,
records or baseline.

## Example

The refund example ships two small batches. The first is healthy:

```bash
decguard check examples/refund/decguard.yaml --dataset examples/refund/production.jsonl
```

```text
DecGuard 0.1.1 · refund_request (choice) · PASS

  Records       4 total · 4 with correctness · 4 with label outcome
  Outcomes      accuracy 1.000 · error 0.000
  Calibration   ECE 0.160 · Brier 0.060 · NLL 0.185
  Confidence    mean 0.840 · p50 0.875 · p95 0.951
  Threshold     confidence >= 0.8: coverage 0.750
  Routing       abstain 0.000 · fallback 0.500 · review 0.250

  Segments
    PASS locale=en · 2 records · accuracy 1.000 · ECE 0.070
    PASS locale=it · 2 records · accuracy 1.000 · ECE 0.250

  Checks
    PASS  min_accuracy                                     accuracy 1 >= 0.9
    PASS  max_ece                                          ece 0.16 <= 0.25
    PASS  min_threshold_coverage                           threshold_coverage 0.75 >= 0.5
    PASS  max_fallback_rate                                fallback_rate 0.5 <= 0.6
    PASS  segment[locale=en].min_accuracy                  segment[locale=en].accuracy 1 >= 0.8
    PASS  segment[locale=it].min_accuracy                  segment[locale=it].accuracy 1 >= 0.8

PASS: all post-deployment gates hold
```

The second is intentionally overconfident and wrong. Checked against the first as
baseline:

```bash
decguard check examples/refund/decguard.yaml \
  --dataset examples/refund/production-drift.jsonl \
  --baseline examples/refund/production.jsonl
```

```text
  Outcomes      accuracy 0.000 · error 1.000
  Calibration   ECE 0.975 · Brier 1.924 · NLL 4.432
  Confidence    mean 0.975 · p50 0.975 · p95 0.989
  ...
  Baseline      dataset · 4 records
  Drift         confidence TV 0.750 · mean delta 0.135 · accuracy drop 1.000 · ECE increase 0.815

  Segments
    FAIL locale=en · 2 records · accuracy 0.000 · ECE 0.985
    FAIL locale=it · 2 records · accuracy 0.000 · ECE 0.965
  ...
FAIL: at least one post-deployment requirement does not hold
```

Confidence went **up** while accuracy collapsed: the pattern that makes an uncalibrated
model dangerous, because a confidence-based policy would automate every one of these
decisions. The run exits `1`.

## Record schema

Production records are backend-neutral: any application can write them, whatever model
it calls. JSONL (one object per line) is recommended; a JSON list is also accepted.

```json
{
  "id": "request-42",
  "timestamp": "2026-09-24T09:00:00Z",
  "decision": "refund_request",
  "input": "The blender arrived damaged.",
  "probabilities": {"refund": 0.96, "reject": 0.01, "review": 0.03},
  "selected": "refund",
  "confidence": 0.96,
  "backend": "openjev",
  "model": "refund-v1",
  "model_version": "2026-09-20",
  "outcome": "refund",
  "outcome_correct": true,
  "latency_ms": 42.0,
  "cost": 0.002,
  "action": "accept",
  "fallback": false,
  "metadata": {"locale": "it", "customer_tier": "pro"}
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `decision` | yes | must equal the contract's `decision.name` |
| `probabilities` | yes | exactly the contract labels; finite, non-negative, summing to 1 within `evaluation.probability_tolerance` |
| `selected` | yes | must be the most probable label (ties to the first in contract order) |
| `id` | no | defaults to `record-<n>` |
| `confidence` | no | defaults to the selected label's probability; must agree with it when given |
| `timestamp` | no | ISO 8601 with a timezone |
| `input` | no | the decision input, string or object |
| `backend`, `model`, `model_version` | no | provenance |
| `outcome` | no | the label actually observed later; DecGuard derives `outcome_correct` from it |
| `outcome_correct` | no | whether the decision turned out right, when the actual label cannot be kept; must agree with `outcome` when both are given |
| `latency_ms`, `cost` | no | non-negative numbers, summarized in the report |
| `action` | no | `accept`, `abstain`, `fallback` or `human_review` — the [policy](./policy.md) route taken |
| `fallback` | no | whether a fallback was used; must agree with `action` when both are given |
| `metadata` | no | an object; scalar values can be used as [segments](#metadata-segments) |

Records are validated strictly, like backend answers: a malformed record stops the check
with exit code `2`, naming the line. Nothing is repaired or skipped. Missing optional
fields stay **unknown**: a record without `outcome` is not counted as wrong, and one
without `action` is not counted as accepted.

`latency_ms`, `cost` and `fallback` are kept in the format so cascade behavior can be
studied without changing it; v0.1 reports them but does not optimize policies.

The runnable samples are
[`production.jsonl`](https://github.com/suffro/decguard/blob/main/examples/refund/production.jsonl)
and
[`production-drift.jsonl`](https://github.com/suffro/decguard/blob/main/examples/refund/production-drift.jsonl).

## Metrics, drift and gates

The report includes:

- **outcomes** — accuracy and error rate (1 − accuracy) over records with known
  correctness;
- **calibration** — ECE over records with known correctness; Brier and NLL where the
  label `outcome` is known;
- **confidence** — histogram, mean and percentiles;
- **threshold coverage** — share at or above `evaluation.confidence_threshold`;
- **routing** — abstention, fallback and human-review rates over records with routing
  information;
- **latency and cost** summaries;
- against a **baseline**: confidence-histogram total variation distance, mean confidence
  delta, accuracy drop and ECE increase.

Production gates are configured separately from pre-deployment golden gates:

```yaml
evaluation:
  confidence_threshold: 0.8

production:
  segments: [locale, customer_tier]
  requirements:
    min_accuracy: 0.95
    max_error_rate: 0.05
    max_ece: 0.05
    min_threshold_coverage: 0.7
    max_fallback_rate: 0.2
    max_confidence_tv_distance: 0.1  # needs --baseline
    max_accuracy_drop: 0.02          # needs --baseline
    max_ece_increase: 0.02           # needs --baseline
  warnings:
    max_abstention_rate: 0.1
  segment_requirements:
    min_accuracy: 0.9
    max_ece: 0.1
  segment_warnings:
    max_fallback_rate: 0.3
```

| Gate | Aggregate | Per segment | Value |
| --- | --- | --- | --- |
| `min_accuracy` | ✓ | ✓ | accuracy over records with known correctness |
| `max_error_rate` | ✓ | ✓ | 1 − accuracy |
| `max_ece` | ✓ | ✓ | expected calibration error |
| `max_brier` | ✓ | ✓ | Brier score (needs `outcome`) |
| `max_nll` | ✓ | ✓ | negative log-likelihood (needs `outcome`) |
| `min_threshold_coverage` | ✓ | ✓ | share at/above `evaluation.confidence_threshold` (required) |
| `max_abstention_rate` | ✓ | ✓ | share of routed records with `action: abstain` |
| `max_fallback_rate` | ✓ | ✓ | share of records that used a fallback |
| `max_confidence_tv_distance` | ✓ | | confidence-histogram TV distance to the baseline |
| `max_accuracy_drop` | ✓ | | baseline − current accuracy |
| `max_ece_increase` | ✓ | | current − baseline ECE |

Aggregate gates go under `requirements` / `warnings`; per-segment gates under
`segment_requirements` / `segment_warnings`. A drift gate without `--baseline` cannot be
computed and therefore does not hold.

## Metadata segments

Each key in `production.segments` creates one group per scalar value found in record
`metadata`, plus a `<missing>` group for records without the key. Segment gates are
evaluated **independently for every group**, so a failure in one locale cannot be hidden
by a healthy aggregate. Objects and arrays are rejected as segment values; this is
deliberately not a general analytics query language.

## Running it on a schedule

`decguard check` fits wherever you already export data: a nightly job, a cron entry, or a
scheduled GitHub Actions workflow that downloads yesterday's records and keeps the report
as an artifact. Pass the previous run's report as `--baseline` to gate on drift. See
[CI](./ci.md#scheduled-production-check).
