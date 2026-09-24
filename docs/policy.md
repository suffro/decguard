# Runtime cascade policy and Python SDK

A policy is an explicit ordered route table. The first matching route wins and the final
route must be unconditional, which makes evaluation total and deterministic.

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

Supported actions are `accept`, `abstain`, `fallback` and `human_review`. A fallback route
must name a backend declared by the same contract. Conditional `confidence_gte` thresholds
must be strictly descending; ambiguous/unreachable routes fail contract validation.

Test one route from the CLI:

```bash
decguard run decguard.yaml "The blender arrived damaged" --format json
```

Embed the identical engine in Python:

```python
from decguard import DecGuard

with DecGuard.from_contract("decguard.yaml") as guard:
    decision = guard.decide("The blender arrived damaged", case_id="request-42")

if decision.action == "accept":
    use(decision.result)
elif decision.action == "fallback":
    enqueue_for(decision.fallback_backend)
elif decision.action == "abstain":
    record_abstention()
else:
    send_to_human_review()
```

`fallback` is an explicit directive; DecGuard v0.1 does not automatically invoke the next
backend. This keeps retry/cost/side-effect control in the embedding application and avoids
turning the policy engine into an implicit optimizer or orchestration service.

`DecGuard.from_contract(..., backend="name")` selects a configured backend. Library users
can instead pass a `DecisionBackend` instance such as `CallableBackend` for an in-process
provider. Backend results still go through the same probability validation used by tests.
