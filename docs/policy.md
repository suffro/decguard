---
description: Deterministic runtime routing on decision confidence - accept, abstain, fallback and human_review - from the CLI and the Python SDK.
---

# Policies and Python SDK

Testing tells you how reliable a model is at each confidence level. A **policy** turns
that into a runtime rule: which decisions the application may act on automatically, and
which it should abstain from, escalate to a stronger model, or send to a person.

A policy is an explicit, ordered route table in the contract. The first matching route
wins and the final route must be unconditional, so every decision gets exactly one action,
deterministically.

```yaml
backends:
  strong_model:
    provider: http
    url: https://strong.example/decide

policy:
  routes:
    - when: {confidence_gte: 0.95}
      action: accept
    - when: {confidence_gte: 0.75}
      action: fallback
      backend: strong_model
    - action: human_review
```

## Actions

| Action | Directive to the application |
| --- | --- |
| `accept` | act on the model's `selected` label |
| `abstain` | do not decide; record the abstention |
| `fallback` | ask the backend named in `backend` (a backend declared in the same contract) |
| `human_review` | send the case to a person |

::: warning Fallback is a directive, not an automatic call
DecGuard v0.1 **does not** invoke the fallback backend. It returns
`action: fallback` and the backend's name; your application decides whether and how to
call it. This keeps retries, cost limits and side effects under the application's control
and keeps the policy engine a pure function rather than an orchestration service.
:::

## Validation rules

The contract is rejected when the policy is ambiguous or incomplete:

- at least one route; the **last** route has no `when`, and only the last;
- `confidence_gte` thresholds (0–1) are **strictly descending**, so no route is
  unreachable;
- `fallback` routes must name a `backend` that the contract declares (`default` or a key of
  `backends`); other actions must not set `backend`.

`confidence_gte` is the only condition in schema 0.1. It compares against the
[normalized confidence](./decisions.md#the-normalized-decisionresult): the selected label's
probability.

## From the CLI

`decguard run` makes one decision with the contract's backend and applies the policy:

```bash
decguard run examples/refund/decguard.yaml "The blender arrived damaged"
decguard run examples/refund/decguard.yaml "The parcel never arrived"
decguard run examples/refund/decguard.yaml "Can someone call me?"
```

```text
accept · selected refund · confidence 0.960 · route 0
fallback -> strong_model · selected refund · confidence 0.900 · route 1
human_review · selected review · confidence 0.650 · route 2
```

`--format json` prints the full result:

```json
{
  "result": {
    "case_id": "runtime",
    "decision": "refund_request",
    "decision_type": "choice",
    "labels": ["refund", "reject", "review"],
    "probabilities": {"refund": 0.9, "reject": 0.02, "review": 0.08},
    "selected": "refund",
    "confidence": 0.9,
    "backend": "default",
    "provider": "mock",
    "model": "refund-mock-v1",
    "model_version": null,
    "latency_ms": 0.0069,
    "metadata": {}
  },
  "action": "fallback",
  "fallback_backend": "strong_model",
  "route_index": 1
}
```

Options: `--backend NAME` to decide with another configured backend, `--input-json` to
pass an object input (`decguard run decguard.yaml '{"text": "..."}' --input-json`),
`--id` to set the case/correlation id (default `runtime`), and `--no-healthcheck`. `run`
exits `0` whatever the action; it exits `2` if the contract has no `policy` or the backend
fails.

## Python SDK

The SDK embeds the same engine in your application:

```python
from decguard import DecGuard

with DecGuard.from_contract("decguard.yaml") as guard:
    decision = guard.decide("The blender arrived damaged", case_id="request-42")

if decision.action == "accept":
    apply(decision.result.selected)
elif decision.action == "fallback":
    enqueue_for(decision.fallback_backend, decision.result)
elif decision.action == "abstain":
    record_abstention(decision.result)
else:  # "human_review"
    send_to_human_review(decision.result)
```

- **`DecGuard.from_contract(contract, *, backend=None, check_health=False)`** loads and
  validates the contract. `contract` is a path; `backend` is the name of a configured
  backend, or a `DecisionBackend` instance such as a
  [`CallableBackend`](./custom-backends.md#python-callable) for an in-process model. It
  raises if the contract has no `policy`.
- **`guard.decide(input, *, case_id="sdk")`** calls the backend, validates the answer with
  the same rules as `decguard test` (including `evaluation.probability_tolerance`), and
  returns a `PolicyDecision`.
- **`PolicyDecision`** has `result` (the [`DecisionResult`](./decisions.md#the-normalized-decisionresult)),
  `action`, `fallback_backend` (set for `fallback` only) and `route_index`.
- Use `DecGuard` as a context manager, or call `close()`, to release the backend's
  connections. A backend instance you pass in is not closed for you.

Backend failures raise `decguard.errors.BackendError` subclasses (`BackendTimeout`,
`BackendUnavailable`, `InvalidResponse`); handle them like any other failed dependency call.

## Choosing thresholds

Pick route thresholds from measured reliability, not intuition:

1. Run [`decguard test`](./metrics.md) with `evaluation.confidence_threshold` set to a
   candidate threshold, and read coverage and selective accuracy.
2. Check the report's calibration bins: a threshold is only meaningful if confidence is
   calibrated around it.
3. After deployment, write the policy's `action` into your [production
   records](./production.md#record-schema) and gate `max_fallback_rate`,
   `max_abstention_rate` and per-segment accuracy with `decguard check`.
