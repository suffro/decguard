"""The unified decision request/result schema and probability validation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from decguard.decisions.types import DecisionSpec, DecisionType
from decguard.errors import InvalidResponse

DecisionInput = str | dict[str, Any]

DEFAULT_PROBABILITY_TOLERANCE = 1e-3


class DecisionRequest(BaseModel):
    """One decision to make: what is asked (``decision``) about which ``input``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    decision: DecisionSpec
    input: DecisionInput


@dataclass(frozen=True)
class Prediction:
    """Raw backend output, before DecGuard validates and normalizes it."""

    probabilities: Mapping[str, float]
    model: str | None = None
    model_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class DecisionResult(BaseModel):
    """A validated decision, identical in shape for every backend.

    ``probabilities`` follows the contract's canonical label order. ``selected`` is the
    most probable label; ties go to the label that comes first in that order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    decision: str
    decision_type: DecisionType
    labels: tuple[str, ...]
    probabilities: dict[str, float]
    selected: str
    confidence: float
    backend: str
    provider: str
    model: str | None = None
    model_version: str | None = None
    latency_ms: float
    metadata: dict[str, Any] = {}


def validate_probabilities(
    labels: tuple[str, ...],
    raw: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_PROBABILITY_TOLERANCE,
) -> dict[str, float]:
    """Check that ``raw`` is a probability distribution over exactly ``labels``.

    Returns the distribution in canonical label order. Values are never rescaled or
    clipped: anything malformed raises :class:`InvalidResponse`.
    """
    if not isinstance(raw, Mapping):
        raise InvalidResponse(f"probabilities must be an object, got {type(raw).__name__}")
    missing = [label for label in labels if label not in raw]
    extra = sorted(str(key) for key in raw if key not in labels)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing labels {missing}")
        if extra:
            parts.append(f"unknown labels {extra}")
        raise InvalidResponse("probabilities do not match the contract labels: " + "; ".join(parts))

    ordered: dict[str, float] = {}
    for label in labels:
        value = raw[label]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidResponse(f"probability for {label!r} is not a number: {value!r}")
        number = float(value)
        if not math.isfinite(number):
            raise InvalidResponse(f"probability for {label!r} is not finite: {number!r}")
        if number < 0.0:
            raise InvalidResponse(f"probability for {label!r} is negative: {number!r}")
        ordered[label] = number

    total = math.fsum(ordered.values())
    if abs(total - 1.0) > tolerance:
        raise InvalidResponse(f"probabilities sum to {total:.6g}, outside 1 ± {tolerance:g}")
    return ordered


def build_result(
    request: DecisionRequest,
    prediction: Prediction,
    *,
    backend: str,
    provider: str,
    latency_ms: float,
    model: str | None = None,
    tolerance: float = DEFAULT_PROBABILITY_TOLERANCE,
) -> DecisionResult:
    """Validate a raw prediction and wrap it in the unified :class:`DecisionResult`."""
    probabilities = validate_probabilities(
        request.decision.labels, prediction.probabilities, tolerance=tolerance
    )
    selected = request.decision.labels[0]
    for label in request.decision.labels:
        if probabilities[label] > probabilities[selected]:
            selected = label
    return DecisionResult(
        case_id=request.case_id,
        decision=request.decision.name,
        decision_type=request.decision.type,
        labels=request.decision.labels,
        probabilities=probabilities,
        selected=selected,
        confidence=probabilities[selected],
        backend=backend,
        provider=provider,
        model=prediction.model or model,
        model_version=prediction.model_version,
        latency_ms=latency_ms,
        metadata=dict(prediction.metadata),
    )
