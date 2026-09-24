"""Explicit deterministic runtime policy configuration."""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field, model_validator

from decguard._validation import StrictModel

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
BackendName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
PolicyAction = Literal["accept", "abstain", "fallback", "human_review"]


class PolicyCondition(StrictModel):
    """A v0.1 route predicate. More predicates can be added in a later schema version."""

    confidence_gte: Probability


class PolicyRoute(StrictModel):
    when: PolicyCondition | None = None
    action: PolicyAction
    backend: BackendName | None = None

    @model_validator(mode="after")
    def _check_backend(self) -> PolicyRoute:
        if self.action == "fallback" and self.backend is None:
            raise ValueError("fallback routes require 'backend'")
        if self.action != "fallback" and self.backend is not None:
            raise ValueError("'backend' is only valid for fallback routes")
        return self


class Policy(StrictModel):
    routes: tuple[PolicyRoute, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_order(self) -> Policy:
        if self.routes[-1].when is not None:
            raise ValueError("the final route must be unconditional")
        if any(route.when is None for route in self.routes[:-1]):
            raise ValueError("only the final route may be unconditional")
        thresholds = [
            route.when.confidence_gte for route in self.routes[:-1] if route.when is not None
        ]
        if any(left <= right for left, right in pairwise(thresholds)):
            raise ValueError("confidence_gte thresholds must be strictly descending")
        return self
