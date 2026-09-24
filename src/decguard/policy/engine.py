"""Pure first-match policy evaluation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from decguard.contracts.policy import Policy, PolicyAction
from decguard.decisions import DecisionResult


class PolicyDecision(BaseModel):
    """A normalized backend decision plus the explicit route selected for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result: DecisionResult
    action: PolicyAction
    fallback_backend: str | None = None
    route_index: int


def apply_policy(policy: Policy, result: DecisionResult) -> PolicyDecision:
    """Evaluate ordered routes. Contract validation guarantees a final default route."""
    for index, route in enumerate(policy.routes):
        if route.when is None or result.confidence >= route.when.confidence_gte:
            return PolicyDecision(
                result=result,
                action=route.action,
                fallback_backend=route.backend,
                route_index=index,
            )
    raise AssertionError("validated policy has no matching route")  # pragma: no cover
