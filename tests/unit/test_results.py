from __future__ import annotations

import math
from typing import Any

import pytest

from decguard.decisions import (
    DecisionRequest,
    DecisionSpec,
    DecisionType,
    Prediction,
    build_result,
    validate_probabilities,
)
from decguard.errors import InvalidResponse

LABELS = ("refund", "reject", "review")
SPEC = DecisionSpec(name="refund_request", type=DecisionType.CHOICE, labels=LABELS)


def test_valid_distribution_is_returned_in_canonical_order() -> None:
    result = validate_probabilities(LABELS, {"review": 0.2, "refund": 0.5, "reject": 0.3})
    assert list(result) == list(LABELS)
    assert result == {"refund": 0.5, "reject": 0.3, "review": 0.2}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"refund": 0.5, "reject": 0.5}, "missing labels ['review']"),
        ({"refund": 0.5, "reject": 0.3, "review": 0.2, "other": 0.0}, "unknown labels ['other']"),
        ({"refund": math.nan, "reject": 0.5, "review": 0.5}, "not finite"),
        ({"refund": math.inf, "reject": 0.0, "review": 0.0}, "not finite"),
        ({"refund": -0.1, "reject": 0.6, "review": 0.5}, "negative"),
        ({"refund": 0.5, "reject": 0.3, "review": 0.3}, "sum to 1.1"),
        ({"refund": "0.5", "reject": 0.3, "review": 0.2}, "not a number"),
        ({"refund": True, "reject": 0.0, "review": 0.0}, "not a number"),
    ],
)
def test_malformed_distributions_are_rejected_not_repaired(
    raw: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidResponse, match=message.replace("[", r"\[").replace("]", r"\]")):
        validate_probabilities(LABELS, raw)


def test_non_mapping_is_rejected() -> None:
    with pytest.raises(InvalidResponse, match="must be an object"):
        validate_probabilities(LABELS, [0.5, 0.5])  # type: ignore[arg-type]


def test_tolerance_is_configurable() -> None:
    raw = {"refund": 0.5, "reject": 0.3, "review": 0.2005}
    assert validate_probabilities(LABELS, raw, tolerance=1e-3)["review"] == 0.2005
    with pytest.raises(InvalidResponse):
        validate_probabilities(LABELS, raw, tolerance=1e-4)


def _result(probabilities: dict[str, float]) -> Any:
    request = DecisionRequest(case_id="c1", decision=SPEC, input="x")
    return build_result(
        request,
        Prediction(probabilities=probabilities, model_version="7"),
        backend="default",
        provider="mock",
        model="m",
        latency_ms=1.5,
    )


def test_build_result_selects_argmax() -> None:
    result = _result({"refund": 0.1, "reject": 0.7, "review": 0.2})
    assert result.selected == "reject"
    assert result.confidence == 0.7
    assert result.labels == LABELS
    assert (result.model, result.model_version, result.latency_ms) == ("m", "7", 1.5)


def test_ties_break_by_canonical_label_order() -> None:
    assert _result({"review": 0.4, "reject": 0.4, "refund": 0.2}).selected == "reject"
    assert _result({"refund": 0.4, "reject": 0.2, "review": 0.4}).selected == "refund"
