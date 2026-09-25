---
description: Probabilistic decisions, the three decision types, the Decision Contract and the normalized DecisionResult every backend produces.
---

# Decisions and results

## Probabilistic decisions

A **decision** is a typed question asked about an input, with a fixed set of possible
answers called **labels**. A probabilistic decision model does not just return an answer:
it returns a probability for every label.

```text
input     "The blender arrived damaged and won't turn on."
question  refund_request: refund, reject or review?
answer    {refund: 0.96, reject: 0.01, review: 0.03}   → selected refund, confidence 0.96
```

DecGuard treats that distribution as the model's output. The **selected** label is the
most probable one and the **confidence** is its probability. Everything DecGuard
measures — accuracy, calibration, coverage, distribution shifts — derives from the
distributions, which is why the contract fixes the set of labels up front.

Inputs are either a string or a JSON object (for example
`{"text": "...", "affected_users": 8000}`).

## Decision types

Three types cover the questions decision models answer. The type decides how labels are
declared and which metrics and properties apply.

### Choice

Pick one of two or more unordered options.

```yaml
decision:
  name: refund_request
  type: choice
  options: [refund, reject, review]
```

### Noul

A yes/no question. `labels` is optional and defaults to `[yes, no]`; the **positive label
comes first**.

```yaml
decision:
  name: is_spam
  type: noul
  labels: [spam, ham]
```

### Score

A level on an ordered scale, listed **from lowest to highest**. Numbers are allowed and
become strings (`1` → `"1"`). Score decisions also get the ordinal error metric
(`ordinal_mae`) and the [`monotonic`](./properties.md#monotonic-score) property.

```yaml
decision:
  name: incident_severity
  type: score
  levels: [1, 2, 3, 4]
```

### Label order

The order in the contract is the **canonical order**. Probabilities in results and
reports always follow it, and when two labels tie for the highest probability, the one
listed first is selected. Labels must be unique, non-empty and have no surrounding spaces.

## The Decision Contract

The contract is the single YAML (or JSON) file that every command reads. Only three keys
are required; each other section adds one capability.

| Section | Purpose | Used by |
| --- | --- | --- |
| `schema_version` | contract format, currently `"0.1"` (required) | all |
| `decision` | name, type and labels (required) | all |
| `backend`, `backends` | the default backend (required) and named alternatives | `test`, `fuzz`, `replay`, `run` |
| `dataset` | golden dataset path | `validate`, `test`, `fuzz` |
| `evaluation` | confidence threshold, calibration bins, probability tolerance, concurrency | all metrics |
| `requirements`, `warnings` | golden-test gates | `test`, `report` |
| `properties`, `fuzz` | metamorphic properties and fuzz settings | `fuzz`, `test --all` |
| `regression` | limits for baseline vs candidate | `diff` |
| `production` | post-deployment gates and metadata segments | `check` |
| `policy` | ordered runtime routes | `run`, Python SDK |

Contracts are data only. They are parsed with a safe YAML loader, reject unknown keys and
duplicate keys, never reference Python import paths, and hold environment-variable
**names**, never secret values. Each report records a `sha256:` hash of the normalized
contract, so formatting changes do not change it but any semantic change does.

The [Decision Contract reference](./contracts.md) lists every field.

## The normalized `DecisionResult`

Every backend's raw answer is validated and normalized into the same structure. This is
one decision from the quickstart, as stored in a report:

```json
{
  "case_id": "r1",
  "decision": "refund_request",
  "decision_type": "choice",
  "labels": ["refund", "reject", "review"],
  "probabilities": {"refund": 0.96, "reject": 0.01, "review": 0.03},
  "selected": "refund",
  "confidence": 0.96,
  "backend": "default",
  "provider": "mock",
  "model": "refund-mock-v1",
  "model_version": null,
  "latency_ms": 0.0073,
  "metadata": {}
}
```

| Field | Meaning |
| --- | --- |
| `case_id` | dataset case id (or the id passed to `run` / the SDK) |
| `decision`, `decision_type`, `labels` | the contract's decision and its canonical labels |
| `probabilities` | one probability per label, in canonical order |
| `selected`, `confidence` | the most probable label (ties to the first) and its probability |
| `backend`, `provider` | the contract's backend name (`default` or a key of `backends`) and its provider |
| `model`, `model_version` | what the backend reports it served, when known |
| `latency_ms` | time spent in the backend call |
| `metadata` | backend-specific extras (for example token usage); secret-like keys are redacted |

### Validation, never repair

Before a result exists, its probabilities must:

- cover **exactly** the contract's labels, no more and no fewer;
- be finite, non-negative numbers;
- sum to 1 within `evaluation.probability_tolerance` (default `0.001`).

Anything else is an `invalid_response` error for that case. DecGuard never rescales,
clips or fills in probabilities, and never drops a case. Confidence is always derived from
the probabilities: if a provider returns its own "confidence" field, DecGuard ignores it.

The same invariants are re-checked whenever a stored report is loaded, so a tampered or
corrupted report is rejected.

### Errors are results too

A case the backend could not answer is recorded with a typed error instead of a result:

| Kind | Cause |
| --- | --- |
| `timeout` | the backend did not answer within its timeout |
| `unavailable` | connection failure, or a retryable HTTP status after retries |
| `invalid_response` | malformed output, wrong labels, probabilities that do not validate |
| `backend_error` | the backend returned a non-retryable error status (for example HTTP 400 or 500) |
| `exception` | an unexpected exception from a plugin backend |
| `paraphrase_error` | fuzzing only: the paraphrase provider failed for this case |

Errors count toward `error_rate`, which is an [implicit requirement](./gates.md#implicit-gates)
of `0`. If **every** case fails, or the backend's healthcheck reports it unhealthy, the run
stops with exit code `2`: there is nothing to evaluate.

## Backend neutrality

Because every backend produces the same `DecisionResult`, everything downstream — metrics,
gates, fuzz comparisons, regression diffs, policies — is written once and works with any
model. Switching from the mock to a local Kev server or to Jev through OpenRouter changes
the `backend` section and nothing else. Two reports from different backends can be
[diffed](./regression.md) directly.

Adapters stay thin: they translate the request to the model's wire format and return raw
label probabilities. See [Backends](./backends.md).
