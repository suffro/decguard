# Post-deployment checks

`decguard check` analyzes decisions already collected by your application. It is an
offline batch command: it does not call a model, upload data, start a daemon or require a
DecGuard service.

```bash
decguard check decguard.yaml \
  --dataset production.jsonl \
  --baseline previous.jsonl \
  --output production-report.json
```

The baseline may be another production JSONL/JSON dataset or a JSON report previously
written by `decguard check`. Exit codes are the usual `0` pass/warn, `1` failed gate and
`2` invalid configuration, dataset or report.

## Production record schema

JSONL is recommended (one object per line); a JSON list is also accepted. Required fields
are `decision`, `probabilities` and `selected`. `id` defaults to `record-<n>` and
`confidence` defaults to the selected label's probability. All other fields are optional.

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

- Probabilities must contain exactly the contract labels, be finite/non-negative and sum
  to 1 within `evaluation.probability_tolerance`. `selected` and optional `confidence`
  must agree with their argmax; malformed records are rejected, never repaired or skipped.
- `outcome` is the observed label. When present, DecGuard derives `outcome_correct`; if
  both are supplied they must agree. `outcome_correct` alone supports accuracy and ECE
  when the actual label cannot be retained. Brier and NLL require `outcome`.
- `action` is `accept`, `abstain`, `fallback` or `human_review`. Missing routing and outcome
  fields remain unknown; DecGuard does not count them as false.
- `latency_ms`, `cost` and `fallback` are retained so future tooling can study cascades
  without changing this public format. v0.1 does not optimize policies.

The complete runnable sample is
[`examples/refund/production.jsonl`](../examples/refund/production.jsonl).

## Metrics, drift and gates

The report includes:

- accuracy and error rate over records with known correctness;
- ECE over known correctness, plus Brier/NLL where label outcomes exist;
- coverage at `evaluation.confidence_threshold`;
- abstention, fallback and human-review rates over records with routing information;
- confidence histogram/mean/percentiles, latency and cost summaries;
- against a baseline: confidence-histogram total variation, confidence mean delta,
  accuracy drop and ECE increase.

Configure gates separately from pre-deployment golden gates:

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

Each configured metadata key creates one simple group per scalar value (including a
`<missing>` group). Segment gates are evaluated independently for every group, so a
localized failure cannot be hidden by the aggregate. Objects and arrays are rejected as
segment values; this is deliberately not a general analytics query language.
