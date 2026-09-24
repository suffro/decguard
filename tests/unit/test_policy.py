from __future__ import annotations

import pytest

from decguard.contracts import Policy, PolicyCondition, PolicyRoute
from decguard.decisions import DecisionResult, DecisionType
from decguard.policy import apply_policy


def result(confidence: float) -> DecisionResult:
    return DecisionResult(
        case_id="case",
        decision="decision",
        decision_type=DecisionType.CHOICE,
        labels=("yes", "no"),
        probabilities={"yes": confidence, "no": 1.0 - confidence},
        selected="yes",
        confidence=confidence,
        backend="default",
        provider="mock",
        latency_ms=1.0,
    )


POLICY = Policy(
    routes=(
        PolicyRoute(
            when=PolicyCondition(confidence_gte=0.95),
            action="accept",
        ),
        PolicyRoute(
            when=PolicyCondition(confidence_gte=0.75),
            action="fallback",
            backend="strong_model",
        ),
        PolicyRoute(action="human_review"),
    )
)


@pytest.mark.parametrize(
    ("confidence", "action", "backend", "index"),
    [
        (0.96, "accept", None, 0),
        (0.95, "accept", None, 0),
        (0.80, "fallback", "strong_model", 1),
        (0.75, "fallback", "strong_model", 1),
        (0.60, "human_review", None, 2),
    ],
)
def test_policy_routes_first_match(
    confidence: float, action: str, backend: str | None, index: int
) -> None:
    routed = apply_policy(POLICY, result(confidence))
    assert (routed.action, routed.fallback_backend, routed.route_index) == (
        action,
        backend,
        index,
    )


def test_policy_supports_abstain() -> None:
    policy = Policy(routes=(PolicyRoute(action="abstain"),))
    assert apply_policy(policy, result(0.7)).action == "abstain"


@pytest.mark.parametrize(
    "routes",
    [
        (PolicyRoute(action="accept"), PolicyRoute(action="human_review")),
        (
            PolicyRoute(
                when=PolicyCondition(confidence_gte=0.8),
                action="accept",
            ),
        ),
        (
            PolicyRoute(
                when=PolicyCondition(confidence_gte=0.7),
                action="accept",
            ),
            PolicyRoute(
                when=PolicyCondition(confidence_gte=0.8),
                action="fallback",
                backend="strong_model",
            ),
            PolicyRoute(action="human_review"),
        ),
    ],
)
def test_policy_rejects_ambiguous_or_unreachable_routes(
    routes: tuple[PolicyRoute, ...],
) -> None:
    with pytest.raises(ValueError, match=r"final route|only the final|strictly descending"):
        Policy(routes=routes)
